#!/usr/bin/env python3
"""Lane correctness receipts. Never invokes gate.sh or a performance instrument."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import aoffix2 as h


def run(label, argv, output, timeout=900, expected=0, env=None):
    cmd = ['taskset', '-c', '104-111', *map(str, argv)]
    start = time.monotonic()
    with (output / (label + '.log')).open('w') as log:
        try:
            rc = subprocess.run(cmd, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                timeout=timeout, env=env).returncode
        except subprocess.TimeoutExpired:
            rc = 124
    row = dict(label=label, argv=cmd, rc=rc, expected=expected,
               seconds=round(time.monotonic() - start, 3))
    with (output / 'runs.jsonl').open('a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)
    return rc == expected


def repro(a):
    out = a.output
    ok = True
    for i in range(10):
        name = f'r2-{i:02}'
        ok &= run(name, ['python3', 'tests/publishfix_e2e.py', '--binary', a.parked,
                        '--artifacts', out / name, '--port', '25810'], out,
                  expected=1 if a.arm == 'pre' else 0)
    for mode, db, policy, count, port in [('1s', 16, 'always', 300, 25820),
                                         ('2s', 1, 'everysec', 100, 25830)]:
        failures = windows = holds = visibility = 0
        for i in range(count):
            name = f'r3-{mode}-{db}-{policy}-{i:03}'
            good = run(name, ['python3', 'tests/aoforder.py', '--case', 'crossing',
                            '--binary', a.scheduled, '--mode', mode, '--databases', db,
                            '--policy', policy, '--cores', '96-103', '--port', port,
                            '--artifacts', out / name], out)
            failures += not good
            events = out / name / 'events.jsonl'
            for line in events.read_text().splitlines() if events.exists() else []:
                r = json.loads(line)
                if r['event'] == 'visibility':
                    windows += r['commit_windows'] > 0
                    holds += r['atomic_commit_holds'] > 0
                    visibility += r['live'] != r['live2']
        row = dict(arm=a.arm, mode=mode, databases=db, policy=policy, runs=count,
                   failures=failures, windows_witnessed=windows,
                   holds_witnessed=holds, visibility_failures=visibility)
        with (out / 'r3-summary.jsonl').open('a') as f:
            f.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
        if a.arm != 'pre':
            ok &= failures == 0
    return ok


def aoforder(a):
    ok = True
    for case in ('single', 'crossing', 'rewrite'):
        binary = a.scheduled if case == 'crossing' else a.binary
        for mode in ('1s', '2s'):
            for db in (1, 16):
                for policy in ('everysec', 'always'):
                    name = f'{case}-{mode}-{db}-{policy}'
                    ok &= run(name, ['python3', 'tests/aoforder.py', '--case', case,
                                    '--binary', binary, '--mode', mode, '--databases', db,
                                    '--policy', policy, '--cores', '96-103', '--ratio', '6:2',
                                    '--port', 25840, '--artifacts', a.output / name], a.output)
            if case == 'single':
                for op in ('MSETNX', 'DEL', 'UNLINK', 'RENAME', 'LMPOP'):
                    name = f'{case}-{mode}-{op}'
                    ok &= run(name, ['python3', 'tests/aoforder.py', '--case', case,
                                    '--operation', op, '--binary', binary, '--mode', mode,
                                    '--policy', 'always', '--cores', '96-103', '--ratio', '6:2',
                                    '--port', 25840, '--artifacts', a.output / name], a.output)
    return ok


def batteries(a):
    ok = True
    for mode in ('1s', '2s'):
        for atomic in (0, 1):
            out = a.output / f'{mode}-a{atomic}'
            out.mkdir()
            h.ARGS = SimpleNamespace(artifacts=out, binary=a.binary.resolve(),
                                    cores='96-103', port=25850, oracle=False, mode=mode,
                                    ratio='6:2', engine='uring')
            with h.Server(['--atomic', str(atomic)]) as server:
                assert server.ready
                for test in ('atomic_torn', 'atomic_ryow', 'atomic_hazards',
                             'execatomic', 'execiso', 'execfix', 'multires', 'multirace',
                             'session_monotonic'):
                    # Each battery may CONFIG SET atomic internally. Restore the requested
                    # initial state for every invocation, and record that state explicitly.
                    c = server.client()
                    assert c.cmd('CONFIG', 'SET', 'atomic', str(atomic)) == b'OK'
                    h.emit('battery', name=test, initial_atomic=atomic, mode=mode)
                    argv = ['python3', f'tests/{test}.py', '127.0.0.1', '25850']
                    if test == 'atomic_torn':
                        argv.append('--release-build')
                    ok &= run(test, argv, out)
            ok &= run('shutdown', ['python3', 'tests/shutdown_report.py', server.logpath, 'clean'], out)
    return ok


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('repro', 'aoforder', 'batteries'))
    p.add_argument('--arm', choices=('pre', 'post'), default='post')
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--parked', type=Path)
    p.add_argument('--scheduled', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    assert set(os.sched_getaffinity(0)) <= set(range(104, 112))
    a.output = a.output.resolve()
    assert a.output.is_relative_to(ROOT)
    a.output.mkdir(parents=True, exist_ok=False)
    if a.binary.exists():
        (a.output / 'binary.sha256').write_text(hashlib.sha256(a.binary.read_bytes()).hexdigest() + '\n')
    raise SystemExit(not globals()[a.phase](a))


if __name__ == '__main__':
    main()
