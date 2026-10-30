#!/usr/bin/env python3
"""Lane-confined correctness receipts through whole gate jobs; never perf/full gate."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/trackorder/runs'
ENV = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
           GATE_PROOF_NO_RATES='1', GATE_TEST_PORT='20198',
           GATE_LOAD_CORES='8-15', GATE_DIFFER_ORACLE_CORES='0-7')


def run(label, command, **env):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / label
    assert not path.with_suffix('.json').exists(), 'preserve previous receipts'
    values = dict(ENV, **env)
    command = ['taskset', '-c', '0-15', *map(str, command)]
    print('START', label, flush=True)
    with path.with_suffix('.log').open('w') as log:
        result = subprocess.run(command, cwd=ROOT, env=values, stdout=log, stderr=subprocess.STDOUT)
    receipt = dict(argv=command, env={k: v for k, v in values.items() if k.startswith('GATE_') or
                                    k in ('LC_ALL', 'REDIS74_ROOT')}, rc=result.returncode)
    for arm in ('PRE', 'POST', 'PAD-A'):
        receipt[arm] = hashlib.sha256((ROOT / ('build/tomokv-' + arm)).read_bytes()).hexdigest()
    path.with_suffix('.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('END', label, result.returncode, flush=True)


def gate(label, jobs, arm='POST', tier='quick', **env):
    run(label, ['bash', 'tests/gate.sh', tier, '--server-cores', '0-7', '--load-cores', '8-15',
                '--ports', '20100-20109', '--candidate-binary', 'build/tomokv-' + arm],
        GATE_ONLY_JOBS=jobs, GATE_LEDGER=str(OUT / (label + '.tsv')), **env)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=('matrices', 'batteries', 'differ', 'tcl'))
    args = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(16))
    if args.phase == 'matrices':
        for arm in ('PRE', 'POST', 'PAD-A'):
            gate('matrix-' + arm, 'trackorder', arm)
    elif args.phase == 'batteries':
        while (ROOT / 'build/trackorder/units-running').exists():
            time.sleep(1)
        ordinary = ('feature-split-0 feature-split-1 feature-armed-0 feature-armed-1 '
                    'fused-0 fused-1 notify clientfix climonfix '
                    'txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1 '
                    'txn_group_split txn_group_fused')
        matrix = ('pubtrackfix trackfix_order trackfix_accounting tracking_redirect notifycompat '
                  'notify_order notify_aof atomic_units netcmd_units txnorder_index '
                  'txnorder_wound txnorder_wake txnorder2 bugs5')
        gate('batteries-uring', ordinary + ' ' + matrix, GATE_NET_IO='uring')
        gate('batteries-epoll', ordinary, GATE_NET_IO='epoll')
    elif args.phase == 'differ':
        for engine in ('epoll', 'uring'):
            gate('differ-' + engine, 'differ-split differ-armed', tier='iteration',
                 GATE_DIFFER_NET_IO=engine, GATE_NET_IO=engine)
    else:
        gate('tcl-tracking', 'redis_tcl', GATE_TCL_MANIFEST='docs/trackorder/tcl-tracking.json')
        gate('tcl-tracking-full', 'redis_tcl', GATE_TCL_MANIFEST='docs/trackorder/tcl-tracking-full.json')


if __name__ == '__main__':
    main()
