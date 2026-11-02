#!/usr/bin/env python3
"""Selected gate jobs on the lane allocation; never run ABBA or a full iteration."""
import argparse
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
GROUPS = {
    'lane': ['atomfix6_units'] + [f'atomfix6-live-{m}-{r}-{d}'
        for m in ('1s', '2s') for r in (0, 1) for d in (1, 16)],
    'units': '''atomic_units core_units exbatch_units splitlocal_units lbplanner_units
        flip_unit flipfix_units flipfix5_units flipfix6_units flushfix2_units flushfix3_units'''.split(),
    'atomic': '''atomic_batteries atomic_floor atomfix5_watch atomfix5_accounting
        release_batteries debug-0 debug-1 fused-0 fused-1 txn_group_fused txn_group_split
        execfair exec1s txnorder_fifo txnorder_fifo_live txnorder_chain txnorder_index txnorder_wound
        txnorder2 txnorder_wake txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1'''.split()
        + ['at412-' + x for x in 'T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11a T11b T12 T13 T14 T15 T16 owner'.split()],
    'features': ['feature-split-0', 'feature-split-1', 'feature-armed-0', 'feature-armed-1',
                 'datafix2_watch', 'moverfix', 'wave14_order', 'clientcompat-multi-tracking',
                 'clientcompat-multi-controls', 'wb_rule_units', 'wbland_units']
        + [f'multifix-{m}-{e}' for m in ('1s', '2s') for e in ('uring', 'epoll')]
        + [f'multidb-{m}-{r}-{a}' for m in ('1s', '2s') for r in (0, 1) for a in (0, 1)],
    'persistence': '''snapshot-epoll snapshot-uring snapfix_shutdown snapfix_bgsave_script
        snapfix_bgsave_exec snapfix2_tables aof-epoll aof-uring aof_frame aoforder dump_restore
        persistfmt persistfmt_aof_error persistfix2_lastsave persistfix2_shutdown
        persistfix2_commands persistfix2_errors persistfix_units flushfix2 flushfix3'''.split(),
    'placement': '''flip fliplisten flipfix5 flipfix6 flipctl
        lb-stationary-1s lb-stationary-2s readonly rlfix3_info rlfix3_zc rlcache
        reorder_engagement reorder_sync exbatch_live rldbg wb_mixed slotless rob_portable'''.split()
        + [f'feature-cell-{m}-{r}-{c}-{q}-{f}' for m in ('1s', '2s') for r in (0, 1)
           for c in (0, 1) for q in (0, 1) for f in (0, 1)]
        + ['feature-cell-split-home-min', 'feature-cell-fused-home-max-nopin', 'feature-cell-split-shards-auto'],
    'differ': ['differ-split', 'differ-armed'],
}
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('group', choices=GROUPS)
p.add_argument('--engine', choices=['uring', 'epoll'], default='uring')
p.add_argument('--fused', action='store_true')
p.add_argument('--label', default='')
a = p.parse_args()
assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
label = a.label or f'{a.group}-{a.engine}-' + ('fused' if a.fused else 'default')
out = ROOT / 'docs/atomfix6/proof' / label
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, LC_ALL='C', GATE_PROOF_NO_RATES='1',
           CXX='g++ -Wl,--compress-debug-sections=zlib',
           GATE_ONLY_JOBS=' '.join(GROUPS[a.group]), GATE_NET_IO=a.engine,
           GATE_PROOF_NET_IO=a.engine, GATE_DIFFER_NET_IO=a.engine,
           GATE_TXN_FUSED=str(int(a.fused)), GATE_LEDGER=str(out / 'ledger.tsv'),
           REDIS74_ROOT='/home/user/Projects/redis',
           GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
           GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli',
           GATE_DIFFER_ORACLE_CORES='74-81')
argv = ['taskset', '-c', '74-86', 'tests/gate.sh', 'full', '--server-cores', '74-81',
        '--load-cores', '82-86', '--load-smt', '', '--server-smt', '',
        '--ports', '21740-21749', '--candidate-binary', str(ROOT / 'build/tomokv')]
(out / 'request.json').write_text(json.dumps(dict(argv=argv,
    env={k: v for k, v in env.items() if k.startswith(('GATE_', 'REDIS74_', 'LC_ALL'))}), indent=2) + '\n')
with (out / 'gate.log').open('w') as log:
    result = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
(out / 'exit.json').write_text(json.dumps(dict(rc=result.returncode)) + '\n')
print(label, 'exit', result.returncode, 'log', out / 'gate.log', flush=True)
raise SystemExit(result.returncode)
