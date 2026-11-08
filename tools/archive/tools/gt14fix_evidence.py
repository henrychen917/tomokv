#!/usr/bin/env python3
"""Collect gt14fix subset evidence; never launches a server or changes test results."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root, expected, test_revision):
    out = root / 'docs/gt14fix/repeat'
    revision = subprocess.check_output(['git', 'rev-parse', test_revision], cwd=root, text=True).strip()
    sources = {name: subprocess.check_output(['git', 'show', revision + ':tests/' + name], cwd=root)
               for name in ('atomic_torn.py', 'xscript.py')}
    includes_held_read = b'rename_on[1] + held_on[1]' in sources['atomic_torn.py']
    rows = []
    progress = (root / 'build/gt14fix/repeat-progress.log').read_text()
    for log in sorted(out.glob('run-*.log')):
        text = log.read_text()
        match = re.search(r'^  artifacts: (.+)$', text, re.M)
        tally = re.search(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;', text)
        if not match or not tally:
            raise AssertionError(f'incomplete subset: {log}')
        passed, failed = map(int, tally.groups())
        assert passed + failed == 19, (log, passed, failed)
        run = Path(match[1])
        plan = (run / 'plan.sh').read_text()
        for setting in ('GATE_RATIO=6:2', 'GATE_SERVER_CORES=112-119',
                        'GATE_LOAD_CORES=120-127', "GATE_SERVER_SMT=''", "GATE_LOAD_SMT=''"):
            assert setting in plan, (run, setting)
        row = {'run': int(log.stem.split('-')[1]), 'artifact_directory': str(run)}
        exit_match = re.search(rf"Repetition {row['run']:02d} exit=(\d+) at ", progress)
        assert exit_match, (run, 'missing subset exit')
        row.update(subset_exit=int(exit_match[1]), passed=passed, failed=failed)
        assert row['subset_exit'] == int(failed > 0), (run, 'cleanup/exit mismatch')
        for job, total in [('debug-1', 14), ('atomic_batteries', 4)]:
            directory = run / 'jobs' / job
            done = (directory / 'done').read_text().split()
            assert len(done) == 3 and done[0] == '0', (directory, done)
            job_passed, job_failed = map(int, done[1:])
            assert job_passed + job_failed == total, (directory, done)
            fields = (directory / 'family.tsv').read_text().split()
            row[job + '_seconds'] = round(float(fields[3]) - float(fields[2]), 3)
            row[job] = {'body_exit': 0, 'passed': job_passed, 'failed': job_failed}
            if job_failed:
                for failure_log in sorted(directory.glob('gate-*.txt')):
                    if '  FAIL ' in failure_log.read_text():
                        (out / f'{log.stem}-{failure_log.name}').write_bytes(failure_log.read_bytes())
        atomic = (run / 'jobs/atomic_batteries/gate-atomic-torn.txt').read_text()
        script = (run / 'jobs/debug-1/gate-xscript-1.txt').read_text()
        off = re.search(r'^  ok   OFF control exposes torn RENAME invalid=(\d+) reads=(\d+)', atomic, re.M)
        on = re.search(r'^  ok   ON RENAME/MGET has exactly one live image invalid=(\d+) reads=(\d+)', atomic, re.M)
        retry = re.search(r'^  ok   contention detector forced at least one OCC restart retries=\+(\d+) errors=\[\]', script, re.M)
        assert off and off.groups() == ('1', '1'), (run, 'OFF witness')
        assert on and on[1] == '0', (run, 'ON witness')
        hammer_reads = int(on[2]) - int(includes_held_read)
        assert hammer_reads > 0, (run, 'original ON hammer read witness')
        assert retry and int(retry[1]) >= 1, (run, 'OCC witness')
        assert atomic.rstrip().endswith('ATOMIC_TORN PASS'), run
        assert script.rstrip().endswith('XSCRIPT all directed battery passed'), run
        row.update(off_invalid=int(off[1]), off_reads=int(off[2]), on_invalid=int(on[1]),
                   on_reported_reads=int(on[2]), on_hammer_reads=hammer_reads,
                   occ_retries=int(retry[1]))
        for label, contents in [('atomic_torn', atomic), ('xscript', script)]:
            target = out / f'{log.stem}-{label}.log.gz'
            with gzip.GzipFile(str(target), 'wb', mtime=0) as f:
                f.write(contents.encode())
            row[label + '_sha256'] = hashlib.sha256(contents.encode()).hexdigest()
        (out / f'{log.stem}.ledger').write_bytes((run / 'ledger.partial').read_bytes())
        rows.append(row)
    assert len(rows) == expected, (len(rows), expected)
    assert [r['run'] for r in rows] == list(range(1, expected + 1))
    job_passes = {job: sum(r[job]['failed'] == 0 for r in rows)
                  for job in ('debug-1', 'atomic_batteries')}
    result = {'completed': len(rows), 'target_batteries_passed': len(rows),
              'whole_job_passes': job_passes, 'failed_gate_rows': sum(r['failed'] for r in rows),
              'passed_gate_rows': sum(r['passed'] for r in rows), 'gate_rows_per_run': 19,
              'server_cpus': '112-119', 'client_cpus': '120-127', 'shards': 16, 'ratio': '6:2',
              'binary_sha256': sha(root / 'build/tomokv'),
              'test_revision': revision, 'on_reported_reads_include_held_read': includes_held_read,
              'test_sha256': {name: hashlib.sha256(source).hexdigest()
                             for name, source in sources.items()}, 'runs': rows}
    audited = json.loads((root / 'docs/gt14fix/artifacts.json').read_text())
    assert result['binary_sha256'] == audited['POST']['binary_sha256'], 'candidate differs from byte-audited POST'
    (out / 'progress.log').write_text(progress)
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'{len(rows)}/{expected} for each target battery; whole jobs: {job_passes}; '
          f"{result['passed_gate_rows']} passing / {result['failed_gate_rows']} failed gate rows")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', type=int, default=30)
    parser.add_argument('--test-revision', required=True, help='revision whose test files ran in this campaign')
    args = parser.parse_args()
    collect(Path(__file__).resolve().parents[1], args.expected, args.test_revision)
