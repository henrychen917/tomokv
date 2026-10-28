#!/usr/bin/env python3
"""Run named correctness jobs through gate.sh's real interface, never a full tier.

Invoke after this lane's tracing/build/live-preemption children have finished:
  taskset -c 32-47 python3 tools/woundfix_gate.py runtime
  taskset -c 32-47 python3 tools/woundfix_gate.py differential
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/woundfix/gate'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', choices=('wounds', 'watch-units', 'runtime', 'differential', 'sanitizers'))
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cells = []
    if args.suite == 'wounds':
        cells.append(('wounds', 'uring', 0, 'quick', 'txnorder_wound'))
    elif args.suite == 'watch-units':
        cells.append(('watch-units', 'uring', 0, 'quick', 'exbatch_units'))
    elif args.suite == 'runtime':
        for engine in ('uring', 'epoll'):
            for fused in (0, 1):
                jobs = 'debug-0 debug-1 atomic_batteries release_batteries script_bounds'
                if not fused:
                    jobs += (' fused-0 fused-1 txn_group_split txn_group_fused'
                             ' txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1'
                             ' atomfix5_watch atomfix5_accounting datafix2_watch exbatch_live atomic_floor')
                    if engine == 'uring': jobs += ' execfair exbatch_units'
                cells.append((f'runtime-{engine}-fused{fused}', engine, fused, 'quick', jobs))
                cells.append((f'script-bounds-{engine}-fused{fused}-a0', engine, fused, 'quick', 'script_bounds'))
    elif args.suite == 'sanitizers':
        for engine in ('uring', 'epoll'):
            for fused in (0, 1):
                cells.append((f'asan-{engine}-fused{fused}', engine, fused, 'full', 'asan_batteries'))
    else:
        for engine in ('uring', 'epoll'):
            cells.append((f'differ-{engine}', engine, 0, 'full', 'differ-split differ-armed'))
    rows = []
    for label, engine, fused, tier, jobs in cells:
        directory = OUT / label; directory.mkdir(exist_ok=True)
        env = dict(os.environ, GATE_ONLY_JOBS=jobs, GATE_PROOF_NO_RATES='1',
                   GATE_PROOF_NET_IO=engine, GATE_TXN_FUSED=str(fused),
                   GATE_TXN_ATOMIC='0' if label.endswith('-a0') else '1',
                   GATE_DIFFER_NET_IO=engine, GATE_DIFFER_ORACLE_CORES='40-45',
                   REDIS74_ROOT='/home/user/Projects/redis')
        cmd = ['tests/gate.sh', tier, '--server-cores', '32-45', '--load-cores', '46-47',
               '--server-smt', '', '--load-smt', '', '--ports', '20301-20359']
        digest = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
        with (directory / 'gate.log').open('w') as log:
            result = subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        assert hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest() == digest, 'binary changed'
        text = (directory / 'gate.log').read_text()
        match = re.search(r'artifacts: (\S+)', text)
        run = Path(match[1]) if match else None
        for name in ('ledger.partial', 'plan.sh', 'phases.tsv', 'families.tsv', 'timings.partial'):
            if run and (run / name).exists(): shutil.copy2(run / name, directory / name)
        result_match = re.search(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL', text)
        counts = list(map(int, result_match.groups())) if result_match else None
        rows.append(dict(label=label, command=cmd, environment={k:env[k] for k in (
            'GATE_ONLY_JOBS', 'GATE_PROOF_NO_RATES', 'GATE_PROOF_NET_IO', 'GATE_TXN_FUSED', 'GATE_TXN_ATOMIC',
            'GATE_DIFFER_NET_IO', 'GATE_DIFFER_ORACLE_CORES', 'REDIS74_ROOT')},
            sha256=digest, exit=result.returncode, counts=counts, artifacts=str(run)))
        (OUT / (args.suite + '.json')).write_text(json.dumps(rows, indent=2) + '\n')
        print(label, 'exit', result.returncode, 'counts', counts, 'artifacts', run, flush=True)
    raise SystemExit(int(any(row['exit'] or not row['counts'] or row['counts'][1] for row in rows)))


if __name__ == '__main__': main()
