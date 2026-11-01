#!/usr/bin/env python3
"""Run whole correctness jobs on the lane CPUs/ports; retain every verdict."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import blockfix2_receipts as receipts

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/blockfix4/gate-receipts'
old_selected = receipts.selected
receipts.selected = lambda p, root: old_selected(p, root) or p.suffix == '.jsonl'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True)
    p.add_argument('--engine', choices=['uring', 'epoll'], required=True)
    p.add_argument('--jobs', default=(ROOT / 'docs/blockfix4/required-jobs.txt').read_text().strip())
    p.add_argument('--fused-debug', action='store_true')
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--ports', default='20200-20299')
    a = p.parse_args()
    lo, hi = map(int, a.ports.split('-'))
    assert 20200 <= lo <= hi <= 20299
    OUT.mkdir(parents=True, exist_ok=True)
    assert not (OUT / (a.tag + '.json')).exists(), a.tag
    binary = a.binary.resolve()
    env = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
               GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
               GATE_PROOF_NO_RATES='1', GATE_NET_IO=a.engine,
               GATE_PROOF_NET_IO=a.engine, GATE_DIFFER_NET_IO=a.engine,
               GATE_ONLY_JOBS=a.jobs, GATE_LEDGER=str(OUT / a.tag))
    if a.fused_debug:
        env['GATE_TXN_FUSED'] = '1'
    command = ['taskset', '-c', '32-47', 'tests/gate.sh', 'push',
               '--server-cores', '32-39', '--load-cores', '40-47',
               '--server-smt', '', '--load-smt', '', '--ports', a.ports,
               '--candidate-binary', str(binary)]
    before = set((ROOT / 'build').glob('gate-run.*'))
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    with (OUT / (a.tag + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    created = set((ROOT / 'build').glob('gate-run.*')) - before
    assert len(created) == 1, created
    record = receipts.collect(a.tag, created.pop(), OUT)
    record.update(command=command, env={k: v for k, v in env.items()
                  if k.startswith('GATE_') or k in ('LC_ALL', 'REDIS74_ROOT')},
                  binary_sha256=digest, exit_code=result.returncode)
    assert digest == hashlib.sha256(binary.read_bytes()).hexdigest(), 'candidate changed during proof'
    (OUT / (a.tag + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(a.tag, result.returncode, sum(j['passed'] for j in record['jobs']),
          sum(j['failed'] for j in record['jobs']), flush=True)


if __name__ == '__main__':
    main()
