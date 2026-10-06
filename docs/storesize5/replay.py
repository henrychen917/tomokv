#!/usr/bin/env python3
"""Serial, CPU-fenced execution of the gate's complete differential inventory.

Atomic-zero parts use the unchanged AT15b replay wrapper; the other parts use
the same differ_gate.sh directly. Completion files describe actual subprocess
results. The gate's strict structural fold validates every executed leg; these
serial lane receipts do not apply the parallel gate's wall-time budget.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / 'tests'))
from differ_fanout import PARTS, fold, load_plan

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', type=Path)
parser.add_argument('--part', choices=PARTS)
args = parser.parse_args()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
plan_path = ROOT / 'docs/at15b/differ-plan.json'
plan = load_plan(plan_path)
binary = ROOT / 'build/storesize5/POST/tomokv'
alias = ROOT / 'build/at15b-post'
if not alias.exists():
    alias.symlink_to(binary)
assert alias.resolve() == binary.resolve(), 'AT15b wrapper must use this candidate'
digest = hashlib.sha256(binary.read_bytes()).hexdigest()
env = dict(os.environ, GATE_LOAD_CORES='121-127', GATE_DIFFER_ORACLE_CORES='120',
           GATE_DIFFER_PLAN=str(plan_path), GATE_RUN_ID='storesize5',
           GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
           GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli')
parts = [args.part] if args.part else ['split-0', 'armed-0', 'split-1', 'armed-1', 'equivalence']
failed = False
for part in parts:
    directory = out / 'jobs' / ('differ-' + part)
    directory.mkdir(parents=True, exist_ok=False)
    destination = directory / 'differ'
    if part in ('split-0', 'armed-0'):
        command = ['bash', 'docs/at15b/replay.sh',
                   'post-split' if part == 'split-0' else 'post-armed', str(destination)]
    else:
        command = ['taskset', '-c', '112-127', 'tests/differ_gate.sh', str(binary),
                   '17899', '17900', '112-119', '6:2']
    child_env = dict(env, GATE_DIFFER_PART=part, GATE_DIFFER_OUT=str(destination),
                     GATE_DIFFER_GEOMETRY='armed-fused' if part.startswith('armed') else 'split')
    started = time.time()
    print('START', part, ' '.join(command), flush=True)
    with (directory / 'output.log').open('w') as log:
        result = subprocess.run(command, env=child_env, stdout=log, stderr=subprocess.STDOUT)
    ended = time.time()
    passed = result.returncode == 0 and (destination / 'complete.json').exists()
    (directory / 'done').write_text(f'{result.returncode}\t{int(passed)}\t{int(not passed)}\n')
    (directory / 'ledger').write_text(('ok' if passed else 'FAIL') + f'\t{part}\t0\n')
    (directory / 'family.tsv').write_text(f'differ-{part}\t{os.getpid()}\t{started:.6f}\t{ended:.6f}\n')
    (directory / 'invocation.json').write_text(json.dumps(dict(
        command=command, binary=str(binary), sha256=digest, exit=result.returncode,
        target_cores='112-119', oracle_cores='120', client_cores='121-127'), indent=2) + '\n')
    failed |= not passed
    print('END', part, 'PASS' if passed else 'FAIL', f'{ended-started:.3f}s', flush=True)

for group in ('split', 'armed'):
    required = [group + '-0', group + '-1'] + (['equivalence'] if group == 'split' else [])
    if not all((out / 'jobs' / ('differ-' + part) / 'done').exists() for part in required):
        continue
    try:
        receipt = fold(plan, group, out)
        receipt['verdict'] = 'PASS'
    except (ValueError, OSError, KeyError, TypeError) as error:
        receipt = dict(group=group, complete=False, verdict='FAIL', error=str(error))
        failed = True
    receipt['scope'] = 'strict gate inventory fold; serial lane run, no parallel wall-time budget'
    (out / ('differ-' + group + '-fold.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
raise SystemExit(int(failed))
