#!/usr/bin/env python3
"""Lane maxmemrace correctness proof through tests/gate.sh's own job interface.

Selected jobs only (GATE_ONLY_JOBS): no ABBA, NIC or full iteration. CPUs 32-47
(server 32-39, load 40-47), ports 20310-20399. Each stage keeps its full gate log.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/maxmemrace/proof'
DOC = ROOT / 'docs/maxmemrace'
ORACLE = '/home/user/Projects/redis/src/redis-server'


def gate(name, tier, jobs, binary, engine='uring', expect=0):
    env = os.environ.copy()
    env.update(REDIS74_ROOT='/home/user/Projects/redis', GATE_DIFFER_ORACLE_BIN=ORACLE,
               GATE_ONLY_JOBS=jobs, GATE_DIFFER_NET_IO=engine, GATE_NET_IO=engine)
    command = ['tests/gate.sh', tier, '--server-cores', '32-39', '--load-cores', '40-47',
               '--ports', '20310-20399', '--candidate-binary', binary]
    log = OUT / f'gate-{name}.log'
    started = time.time()
    print('BEGIN', name, flush=True)
    with log.open('w') as f:
        rc = subprocess.run(command, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
    tail = log.read_text(errors='replace').splitlines()[-3:]
    row = dict(name=name, tier=tier, selected_jobs=jobs.split(), binary=binary, engine=engine,
               returncode=rc, expected_returncode=expect, seconds=round(time.time() - started, 1),
               command=command, log=str(log.relative_to(ROOT)), tail=tail)
    print('END', name, rc, tail[-1] if tail else '', flush=True)
    return row


def main():
    assert os.sched_getaffinity(0) <= set(range(32, 48)), 'run under taskset -c 32-47'
    p = argparse.ArgumentParser()
    p.add_argument('--stages', default='affected,fullonly,differ,controls')
    p.add_argument('--post', default='build/maxmemrace/post/tomokv')
    p.add_argument('--pre', default='build/maxmemrace/pre/tomokv')
    p.add_argument('--pad', default='build/maxmemrace/pad-a/tomokv')
    p.add_argument('--label', default='final')
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    quick = (DOC / 'proof-jobs-quick.txt').read_text().split()
    fullonly = [j for j in (DOC / 'proof-jobs-full.txt').read_text().split()
                if not j.startswith('differ-')]
    results = []
    stages = a.stages.split(',')
    if 'affected' in stages:
        results.append(gate('affected-' + a.label, 'quick', ' '.join(quick), a.post))
    if 'fullonly' in stages:
        results.append(gate('fullonly-' + a.label, 'iteration', ' '.join(fullonly), a.post))
    if 'differ' in stages:
        for engine in ('uring', 'epoll'):
            results.append(gate(f'differ-{engine}-' + a.label, 'iteration',
                                'differ-split differ-armed', a.post, engine))
    if 'controls' in stages:
        results.append(gate('control-pre-' + a.label, 'quick', 'maxmemrace', a.pre, expect=1))
        results.append(gate('control-pad-' + a.label, 'quick', 'maxmemrace', a.pad, expect=1))
    path = DOC / f'proof-driver-{a.label}-{a.stages.replace(",", "-")}.json'
    path.write_text(json.dumps(results, indent=2) + '\n')
    return 0 if all(r['returncode'] == r['expected_returncode'] for r in results) else 1


if __name__ == '__main__':
    sys.exit(main())
