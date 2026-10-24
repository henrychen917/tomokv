#!/usr/bin/env python3
"""Invoke whole gate jobs and retain source, binary, environment and row receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
p = argparse.ArgumentParser()
p.add_argument('name')
p.add_argument('jobs', nargs='+')
p.add_argument('--engine', choices=['epoll', 'uring'], default='uring')
p.add_argument('--fused', action='store_true')
p.add_argument('--atomic', choices=['0', '1'], default='1')
p.add_argument('--root', type=Path, default=ROOT)
p.add_argument('--adapter', action='store_true')
a = p.parse_args()
out = ROOT / 'docs/wave6/correctness' / a.name
out.mkdir(parents=True, exist_ok=False)
binary = ROOT / 'build/tomokv'
source = a.root.resolve()
oracle_root = ROOT / 'build/wave6/redis74-oracle'
(oracle_root / 'src').mkdir(parents=True, exist_ok=True)
for item in Path('/home/user/Projects/redis/src').iterdir():
    target = oracle_root / 'src' / item.name
    if not target.exists():
        target.symlink_to('/home/user/Projects/redis74/src/redis-server'
                          if item.name == 'redis-server' else item)
env = dict(os.environ, REDIS74_ROOT=str(oracle_root),
           GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
           GATE_DIFFER_NET_IO=a.engine, GATE_TEST_PORT='26898',
           GATE_ONLY_JOBS=' '.join(a.jobs), GATE_TXN_FUSED=str(int(a.fused)),
           GATE_TXN_ATOMIC=a.atomic,
           GATE_LEDGER=str(out / 'ledger'))
env.pop('NETFIX_TLS_ORACLE', None)
candidate = binary
if a.adapter:
    candidate = ROOT / 'docs/wave6/server_adapter.py'
    env.update(WAVE6_ENGINE=a.engine, WAVE6_BINARY=str(binary),
               WAVE6_LAUNCH_DIR=str(out / 'launches'))
    if a.fused:
        env['WAVE6_MODE'] = '1s'
command = ['taskset', '-c', '64-95', 'bash', 'tests/gate.sh', 'full',
           '--server-cores', '64-87', '--server-smt', '',
           '--load-cores', '88-95', '--load-smt', '',
           '--ports', '26800-26889', '--candidate-binary', str(candidate)]
receipt = dict(command=command, cwd=str(source), start=time.time(),
               commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
               binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
               gate_sha256=hashlib.sha256((source / 'tests/gate.sh').read_bytes()).hexdigest(),
               environment={k: v for k, v in env.items() if k.startswith(('GATE_', 'WAVE6_', 'REDIS74_'))},
               netfix_tls_oracle='unset: gate default /home/user/Projects/redis74-tls')
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
with (out / 'gate.log').open('w') as log:
    result = subprocess.run(command, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
text = (out / 'gate.log').read_text()
match = re.search(r'artifacts: (.+)', text)
receipt.update(exit=result.returncode, end=time.time(),
               binary_sha256_after=hashlib.sha256(binary.read_bytes()).hexdigest(),
               run_dir=match[1] if match else None)
if match:
    run = Path(match[1])
    receipt['jobs'] = {}
    for job in sorted((run / 'jobs').iterdir()):
        receipt['jobs'][job.name] = dict(
            done=(job / 'done').read_text().strip() if (job / 'done').exists() else None,
            rows=(job / 'ledger').read_text().splitlines() if (job / 'ledger').exists() else [])
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
print(a.name, result.returncode, match[1] if match else 'no run', flush=True)
assert receipt['binary_sha256'] == receipt['binary_sha256_after'], 'candidate changed during job'
raise SystemExit(result.returncode)
