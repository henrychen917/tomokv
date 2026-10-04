#!/usr/bin/env python3
"""Collect gt14fix subset evidence; never launches a server or changes test results."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect(root, expected):
    out = root / 'docs/gt14fix/repeat'
    rows = []
    for log in sorted(out.glob('run-*.log')):
        text = log.read_text()
        match = re.search(r'^  artifacts: (.+)$', text, re.M)
        if not match or 'GATE(PARTIAL): 19 ok, 0 FAIL;' not in text:
            raise AssertionError(f'incomplete or failed subset: {log}')
        run = Path(match[1])
        plan = (run / 'plan.sh').read_text()
        for setting in ('GATE_RATIO=6:2', 'GATE_SERVER_CORES=112-119',
                        'GATE_LOAD_CORES=120-127', "GATE_SERVER_SMT=''", "GATE_LOAD_SMT=''"):
            assert setting in plan, (run, setting)
        row = {'run': int(log.stem.split('-')[1]), 'artifact_directory': str(run)}
        for job, passed in [('debug-1', 14), ('atomic_batteries', 4)]:
            directory = run / 'jobs' / job
            done = (directory / 'done').read_text().split()
            assert done == ['0', str(passed), '0'], (directory, done)
            fields = (directory / 'family.tsv').read_text().split()
            row[job + '_seconds'] = round(float(fields[3]) - float(fields[2]), 3)
            row[job] = {'exit': 0, 'passed': passed, 'failed': 0}
        atomic = (run / 'jobs/atomic_batteries/gate-atomic-torn.txt').read_text()
        script = (run / 'jobs/debug-1/gate-xscript-1.txt').read_text()
        off = re.search(r'^  ok   OFF control exposes torn RENAME invalid=(\d+) reads=(\d+)', atomic, re.M)
        on = re.search(r'^  ok   ON RENAME/MGET has exactly one live image invalid=(\d+) reads=(\d+)', atomic, re.M)
        retry = re.search(r'^  ok   contention detector forced at least one OCC restart retries=\+(\d+) errors=\[\]', script, re.M)
        assert off and off.groups() == ('1', '1'), (run, 'OFF witness')
        assert on and on[1] == '0' and int(on[2]) > 1, (run, 'ON witness')
        assert retry and int(retry[1]) >= 1, (run, 'OCC witness')
        assert atomic.rstrip().endswith('ATOMIC_TORN PASS'), run
        assert script.rstrip().endswith('XSCRIPT all directed battery passed'), run
        row.update(off_invalid=int(off[1]), off_reads=int(off[2]), on_invalid=int(on[1]),
                   on_reads=int(on[2]), occ_retries=int(retry[1]))
        for label, contents in [('atomic_torn', atomic), ('xscript', script)]:
            target = out / f'{log.stem}-{label}.log.gz'
            with gzip.GzipFile(str(target), 'wb', mtime=0) as f:
                f.write(contents.encode())
            row[label + '_sha256'] = hashlib.sha256(contents.encode()).hexdigest()
        (out / f'{log.stem}.ledger').write_bytes((run / 'ledger.partial').read_bytes())
        rows.append(row)
    assert len(rows) == expected, (len(rows), expected)
    assert [r['run'] for r in rows] == list(range(1, expected + 1))
    result = {'completed': len(rows), 'failures': 0, 'gate_rows_per_run': 19,
              'server_cpus': '112-119', 'client_cpus': '120-127', 'shards': 16, 'ratio': '6:2',
              'binary_sha256': sha(root / 'build/tomokv'),
              'test_sha256': {name: sha(root / 'tests' / name)
                             for name in ('atomic_torn.py', 'xscript.py')}, 'runs': rows}
    (out / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(f'{len(rows)}/{expected} atomic_batteries; {len(rows)}/{expected} debug-1; '
          f'{19 * len(rows)} passing gate rows; no failed rows')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected', type=int, default=30)
    args = parser.parse_args()
    collect(Path(__file__).resolve().parents[1], args.expected)
