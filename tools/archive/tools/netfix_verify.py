#!/usr/bin/env python3
"""Run netfix correctness only through gate.sh's job interface, on the lane allocation.

Wrappers select an engine (and, for the otherwise split TLS battery, fused mode).
The gate still owns every process, port, job, row, watchdog and differential seed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
# 'prefix' is a disposable control: the committed tree before the NT4.8 32-bit bound fix.
ARMS = {'pre': 'tomokv-pre-netfix', 'post': 'tomokv', 'pad': 'tomokv-pad-a-netfix',
        'padb': 'tomokv-pad-b-netfix',
        'prefix': 'netfix-prefix-src/build/tomokv'}
NEW = 'netfix_query_stats netfix_unix netfix_config netfix_tls netfix_idle_buffers'
# Jobs that boot the default engine: run once per engine wrapper (or the source build for uring).
REQUIRED = ('tls netcmd_units respcompat config_unit auth authfix notify debug-0 debug-1 '
            'clientfix climonfix feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 '
            'fused-0 fused-1')
# Jobs that already select both engines themselves: run once per arm.
ENGINES = ('netcap ntfix_input netio-1s netio-2s aof-epoll aof-uring ' + ' '.join(
    f'respresume-{case}-{mode}-{engine}' for case in ('fragment', 'cpu', 'neighbour')
    for mode in ('1s', '2s') for engine in ('epoll', 'uring')))


def wrapper(arm, engine, fused=False):
    binary = ROOT / 'build' / ARMS[arm]
    path = ROOT / 'build' / f'netfix-{arm}-{engine}{"-fused" if fused else ""}'
    # exec preserves the PID, so the gate's exact-owner lifetime checks remain valid.
    script = ('#!/usr/bin/env python3\nimport os, sys\n'
              'args = sys.argv[1:]\n'
              'config = [args.pop(0)] if args and not args[0].startswith("--") else []\n')
    if fused:
        script += ('for option in ("--ratio", "--thread-mode"):\n'
                   '    while option in args:\n'
                   '        i = args.index(option)\n'
                   '        del args[i:i+2]\n')
    script += f'os.execv({str(binary)!r}, [{str(binary)!r}] + config + ["--net-io", {engine!r}'
    if fused:
        script += ', "--thread-mode", "1s"'
    script += '] + args)\n'
    path.write_text(script)
    path.chmod(0o755)
    return path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('arm', choices=tuple(ARMS))
    p.add_argument('phase', choices=('new', 'required', 'engines', 'tls-fused', 'differ', 'idle'))
    p.add_argument('--engine', choices=('epoll', 'uring'), default='uring')
    p.add_argument('--port', type=int, required=True)
    p.add_argument('--label', required=True)
    p.add_argument('--jobs', help='explicit gate job subset for an evidence-preserving rerun')
    p.add_argument('--source', action='store_true',
                   help='POST only: no wrapper or --candidate-binary; the gate builds this tree')
    a = p.parse_args()
    assert 20800 <= a.port <= 20897
    os.sched_setaffinity(0, range(64, 80))
    os.chdir(ROOT)
    jobs = {'new': NEW, 'required': REQUIRED, 'engines': ENGINES, 'tls-fused': 'tls',
            'differ': 'differ-split differ-armed', 'idle': 'netfix_idle_buffers'}[a.phase]
    jobs = a.jobs or jobs
    assert not a.source or (a.arm == 'post' and a.engine == 'uring' and a.phase != 'tls-fused')
    binary = None if a.source else wrapper(a.arm, a.engine, a.phase == 'tls-fused')
    actual = ROOT / 'build' / ARMS[a.arm]
    before = hashlib.sha256(actual.read_bytes()).hexdigest()
    env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis',
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
               NETFIX_TLS_ORACLE=str(ROOT / 'build/redis74-tls-jemalloc-server'),
               GATE_ONLY_JOBS=jobs)
    # A preceding owned job may still be finishing its shutdown. Wait for the
    # allocated listener range to become free; never terminate a port occupant.
    deadline = time.monotonic() + 900
    while subprocess.check_output(['ss', '-H', '-ltn',
            f'( sport >= :{a.port} and sport <= :{a.port+2} )'], text=True).strip():
        if time.monotonic() >= deadline:
            raise TimeoutError(f'allocated ports {a.port}-{a.port+2} remained occupied')
        time.sleep(.5)
    cmd = ['bash', 'tests/gate.sh', 'full' if a.phase == 'differ' else 'quick',
           '--server-cores', '64-71', '--load-cores', '72-79', '--load-smt', '',
           '--ports', f'{a.port}-{a.port+2}'] + ([] if a.source else
           ['--candidate-binary', str(binary)])
    fresh = subprocess.run(['make', '-q', 'all']).returncode if a.source else None
    output = ROOT / 'docs/netfix/evidence' / a.label
    assert not output.with_suffix('.log').exists(), 'never overwrite a live or prior gate log'
    with output.with_suffix('.log').open('w') as log:
        result = subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT)
    output.with_suffix('.json').write_text(json.dumps(dict(
        arm=a.arm, phase=a.phase, engine=a.engine, jobs=jobs, command=cmd,
        wrapper=binary.read_text() if binary else None, make_q_all_before=fresh,
        actual_binary=str(actual), sha256_before=before,
        sha256_after=hashlib.sha256(actual.read_bytes()).hexdigest(),
        returncode=result.returncode), indent=2) + '\n')
    raise SystemExit(result.returncode)


if __name__ == '__main__':
    main()
