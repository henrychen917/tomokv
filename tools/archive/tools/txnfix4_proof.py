#!/usr/bin/env python3
"""Run whole gate jobs through tests/gate.sh's partial-job interface on the lane's CPUs and
ports, and retain every verdict (red and green) under docs/txnfix4/gate-receipts/."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blockfix2_receipts as receipts  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/txnfix4/gate-receipts'
old_selected = receipts.selected
receipts.selected = lambda p, root: old_selected(p, root) or p.suffix == '.jsonl'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tag', required=True)
    p.add_argument('--engine', choices=['uring', 'epoll'], required=True)
    p.add_argument('--jobs', required=True)
    p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
    p.add_argument('--tier', default='push')
    p.add_argument('--fused-debug', action='store_true')
    a = p.parse_args()
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
    command = ['taskset', '-c', '61-73', 'tests/gate.sh', a.tier,
               '--server-cores', '61-68', '--load-cores', '69-73',
               '--server-smt', '', '--load-smt', '', '--ports', '21400-21499',
               '--candidate-binary', str(binary)]
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    with (OUT / (a.tag + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    matches = re.findall(r'^  artifacts: (.+)$', (OUT / (a.tag + '.log')).read_text(), re.M)
    assert len(matches) == 1, matches
    run = Path(matches[0]).resolve()
    assert run.parent == ROOT / 'build' and run.name.startswith('gate-run.'), run
    record = receipts.collect(a.tag, run, OUT)
    record.update(command=command, env={k: v for k, v in env.items()
                  if k.startswith('GATE_') or k in ('LC_ALL', 'REDIS74_ROOT')},
                  binary=str(binary), binary_sha256=digest, exit_code=result.returncode)
    assert digest == hashlib.sha256(binary.read_bytes()).hexdigest(), 'candidate changed'
    (OUT / (a.tag + '.json')).write_text(json.dumps(record, indent=2) + '\n')
    print(a.tag, result.returncode, sum(j['passed'] for j in record['jobs']),
          sum(j['failed'] for j in record['jobs']), flush=True)


if __name__ == '__main__':
    main()
