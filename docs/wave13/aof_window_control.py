#!/usr/bin/env python3
"""Remove only the test pause hook; the complete persistfmt gate job must fail."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave13'
DEST = ROOT / 'build/wave13/aof-never-armed'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    assert os.sched_getaffinity(0) <= set(range(16))
    assert 'failure_window_unarmed' in (ROOT / 'tests/persistfmt.py').read_text()
    assert not DEST.exists(), 'Preserve previous control attempts'
    DEST.mkdir(parents=True)
    source = DEST / 'aof.cc'
    subprocess.run(['python3', 'tools/persistfmt_schedule.py', 'src/persist/aof.cc', str(source)],
                   cwd=ROOT, check=True)
    generated_sha = sha(source)
    before = 'if (persistfmt_armed() && persistfmt_schedule.load() < 2) {'
    after = 'if (false && persistfmt_armed() && persistfmt_schedule.load() < 2) {'
    original = source.read_text()
    assert original.count(before) == 1
    source.write_text(original.replace(before, after))
    candidate = ROOT / 'build/wave13/tomokv-POST'
    post_sha = sha(candidate)
    binary = DEST / 'tomokv'
    build = ['make', '-f', 'Makefile', '-f', 'tools/persistfmt.mk', '-j16',
             'PERSISTFMT_SCHEDULE=' + str(DEST.relative_to(ROOT)), str(binary.relative_to(ROOT))]
    with (DEST / 'build.log').open('w') as stream:
        subprocess.run(build, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    record = dict(post_sha256=post_sha, scheduling_control_sha256=sha(binary),
                  generated_source_sha256=generated_sha, modified_source_sha256=sha(source),
                  generator_sha256=sha(ROOT / 'tools/persistfmt_schedule.py'),
                  harness_sha256=sha(ROOT / 'tests/persistfmt.py'), before=before, after=after,
                  build=build, note='Only the gate-owned scheduling twin is mutated; production POST is unchanged.')
    receipt_name = 'negative-aof-never-armed'
    argv = ['python3', 'docs/wave13/run_jobs.py', receipt_name, 'persistfmt',
            '--binary', str(candidate), '--single-slot']
    env = dict(os.environ, GATE_PERSISTFMT_SCHEDULED=str(binary), LC_ALL='C', LANG='C')
    with (DEST / 'gate.log').open('w') as stream:
        result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
    receipt_path = DOC / 'jobs' / (receipt_name + '.json')
    receipt = json.loads(receipt_path.read_text())
    folder = Path(receipt['artifacts']) / 'jobs/persistfmt'
    record.update(exit=result.returncode, receipt=str(receipt_path.relative_to(ROOT)),
                  receipt_sha256=sha(receipt_path), modes=[])
    assert result.returncode == receipt['exit'] == 1
    assert receipt['binary_unchanged'] and receipt['source_tree_unchanged'] and receipt['tests_tools_unchanged']
    assert receipt['binary_sha256'] == post_sha == sha(candidate)
    assert list(map(int, (folder / 'done').read_text().split())) == [1, 36, 4]
    for mode, engine in itertools.product(('1s', '2s'), ('epoll', 'uring')):
        stem = f'persistfmt-aof-failure-{mode}-{engine}'
        events_path = folder / stem / 'events.jsonl'
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        attempts = [e for e in events if e['event'] == 'aof_failure_attempt']
        unarmed = [e for e in events if e['event'] == 'failure_window_unarmed']
        armed = [e for e in events if e['event'] == 'failure_window_armed']
        stops = [e for e in events if e['event'] == 'stop']
        assert len(attempts) == len(unarmed) == len(stops) == 8 and not armed
        assert [e['attempt'] for e in attempts] == list(range(1, 9))
        assert all(e['command'] == 'SET' and e['markers'].keys() == {'fail'} and
                   e['markers']['fail']['stage'] == 0 for e in unarmed)
        assert all(e['exit'] == -9 and not e['escalated'] for e in stops)
        log = folder / (stem + '.log')
        assert 'SET: fail() logging window never opened in 8 fresh attempts' in log.read_text()
        record['modes'].append(dict(mode=mode, engine=engine, attempts=8, armed=0,
                                    events_sha256=sha(events_path), log_sha256=sha(log), verified=True))
    record['verified'] = True
    record['pruned_files'] = []
    for path in sorted(DEST.iterdir()):
        if path == binary or path.suffix in ('.cc', '.o', '.d'):
            record['pruned_files'].append(dict(path=str(path.relative_to(ROOT)), bytes=path.stat().st_size,
                                               sha256=sha(path)))
    output = DOC / 'aof-window-negative-control.json'
    output.write_text(json.dumps(record, indent=2) + '\n')
    for row in record['pruned_files']:
        (ROOT / row['path']).unlink()
    record['pruned'] = True
    output.write_text(json.dumps(record, indent=2) + '\n')
    print('PASS: missing pause hook fails the full persistfmt job in all four mode/engine legs')


if __name__ == '__main__':
    main()
