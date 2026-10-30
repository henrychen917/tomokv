#!/usr/bin/env python3
"""Lane-confined correctness receipts through whole gate jobs; never perf/full gate."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/trackorder/runs'
SERVER_CORES = os.environ.get('TRACKORDER_SERVER_CORES', '0-7')
LOAD_CORES = os.environ.get('TRACKORDER_LOAD_CORES', '8-15')
PORT_BASE = int(os.environ.get('TRACKORDER_PORT_BASE', '20100'))
assert 20100 <= PORT_BASE <= 20190
ENV = dict(os.environ, LC_ALL='C', REDIS74_ROOT='/home/user/Projects/redis',
           GATE_PROOF_NO_RATES='1', GATE_TEST_PORT='20198',
           GATE_LOAD_CORES=LOAD_CORES, GATE_DIFFER_ORACLE_CORES=SERVER_CORES)


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
    run(label, ['bash', 'tests/gate.sh', tier, '--server-cores', SERVER_CORES, '--load-cores', LOAD_CORES,
                '--ports', f'{PORT_BASE}-{PORT_BASE + 9}', '--candidate-binary', 'build/tomokv-' + arm],
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
        with (ROOT / 'build/trackorder/differ.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for engine in ('epoll', 'uring'):
                label = 'differ-' + engine
                if (OUT / (label + '.json')).exists():
                    print(label + ' receipt already complete; preserved', flush=True)
                    continue
                gate(label, 'differ-split differ-armed', tier='iteration',
                     GATE_DIFFER_NET_IO=engine, GATE_NET_IO=engine)
        # Remaining whole jobs with tracking/pubsub/flush-specific witnesses.
        gate('supplementary', 'compat3 wave8b_off infofix_latency storage_units')
    else:
        # A separate allocated port slot can run Tcl beside the ordinary jobs.
        # An automatic second invocation waits for those same immutable receipts.
        with (ROOT / 'build/trackorder/tcl.lock').open('w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if all((OUT / (label + '.json')).exists() for label in ('tcl-tracking', 'tcl-tracking-full')):
                print('Tcl receipts already complete; preserved', flush=True)
                return
            gate('tcl-tracking', 'redis_tcl', GATE_TCL_MANIFEST='docs/trackorder/tcl-tracking.json')
            gate('tcl-tracking-full', 'redis_tcl', GATE_TCL_MANIFEST='docs/trackorder/tcl-tracking-full.json')


if __name__ == '__main__':
    main()
