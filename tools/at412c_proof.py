#!/usr/bin/env python3
"""Run authorized correctness jobs only, on at412c's CPU and port allocation.

Every gate invocation uses its native partial-job scheduler and watchdogs.
No throughput cells or full iteration are run. Failed jobs remain in runs.json.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'build/at412c/proof'

DIRECTED = ['at412-'+x for x in
            ['T1','T2','T3','T4','T5','T6','T7','T8','T9','T10','T11a','T11b',
             'T12','T13','T14','T15','T16','owner']]
TXN = ['txnorder-'+m+'-'+a for m in ('fused','split') for a in ('0','1')]
DEBUG = ['debug-0','debug-1']
FEATURE = ['feature-'+m+'-'+a for m in ('split','armed') for a in ('0','1')]
NOTIFY = ['notify','notifycompat','notify_order','notify_aof','tracking_redirect',
          'trackfix_accounting','trackfix_order']
PERSIST = ['snapshot-epoll','snapshot-uring','aof-epoll','aof-uring',
           'aof_frame','aoforder','persistfix2_lastsave','persistfix2_shutdown',
           'persistfix2_commands','persistfix2_errors','dump_restore','serverfix_waitaof']
PHASES = {
    'directed': (DIRECTED, {}),
    'split-uring': (DEBUG + TXN + FEATURE + NOTIFY + PERSIST +
                    ['txnorder_index','txnorder2','txnorder_wake','txn_group_fused','txn_group_split',
                     'script_bounds','scriptfix','flip','fliplisten','flipctl','flip_saturated',
                     'flip_unit','flipfix_units','persistfix_units','compat2','compat3','clientfix'], {}),
    'split-epoll': (DEBUG + TXN + FEATURE + NOTIFY + ['script_bounds','scriptfix'],
                    {'GATE_PROOF_NET_IO':'epoll'}),
    'fused-uring': (DEBUG + NOTIFY + PERSIST, {'GATE_TXN_FUSED':'1'}),
    'fused-epoll': (DEBUG + NOTIFY, {'GATE_TXN_FUSED':'1', 'GATE_PROOF_NET_IO':'epoll'}),
    'differ-uring': (['differ-split','differ-armed','differ-equivalence'], {}),
    'differ-epoll': (['differ-split','differ-armed','differ-equivalence'],
                     {'GATE_DIFFER_NET_IO':'epoll'}),
}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phases', nargs='+', choices=PHASES)
    args = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    results_file = OUT/'runs.json'
    results = json.loads(results_file.read_text()) if results_file.exists() else []
    for phase in args.phases:
        jobs, extra = PHASES[phase]
        env = dict(os.environ, REDIS74_ROOT='/home/user/Projects/redis74', GATE_TEST_PORT='20299',
                   GATE_ONLY_JOBS=' '.join(jobs), **extra)
        cmd = ['taskset','-c','48-63','bash','tests/gate.sh',
               'full' if phase.startswith('differ-') else 'quick',
               '--server-cores','48-55','--load-cores','56-63',
               '--server-smt','','--load-smt','','--ports','20200-20279']
        log = OUT/f'{phase}-{len(results)}.log'
        row = dict(phase=phase, command=cmd, environment={k:env[k] for k in
                   ['REDIS74_ROOT','GATE_TEST_PORT','GATE_ONLY_JOBS',*extra]},
                   source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                   sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest(),
                   log=str(log), began=time.time())
        with log.open('w') as stream:
            rc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT).returncode
        text = log.read_text()
        run = re.search(r'artifacts: (\S+)', text)
        row.update(rc=rc, seconds=round(time.time()-row['began'],3),
                   run_dir=run[1] if run else None)
        results.append(row)
        results_file.write_text(json.dumps(results,indent=2)+'\n')
        print(json.dumps(row),flush=True)
    return int(any(r['rc'] for r in results[-len(args.phases):]))


if __name__ == '__main__':
    raise SystemExit(main())
