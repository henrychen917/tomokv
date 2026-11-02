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
    'pad': ['atomfix6-live-1s-0-1', 'atomfix6-live-2s-0-16'],
    'fifo': ['txnorder_fifo_live'],
    'park': ['atomfix6_units'],
    'order': ['wave14_order'],
    'notify': ['notify'],
    'units': '''atomic_units core_units exbatch_units splitlocal_units lbplanner_units
        flip_unit flipfix_units flipfix5_units flipfix6_units flushfix2_units flushfix3_units'''.split(),
    'atomic': '''atomic_batteries atomic_floor atomfix5_watch atomfix5_accounting
        release_batteries debug-0 debug-1 fused-0 fused-1 txn_group_fused txn_group_split
        execfair exec1s txnorder_fifo txnorder_fifo_live txnorder_chain txnorder_index txnorder_wound
        txnorder2 txnorder_wake txnorder-fused-0 txnorder-fused-1 txnorder-split-0 txnorder-split-1'''.split()
        + ['at412-' + x for x in 'T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11a T11b T12 T13 T14 T15 T16 owner'.split()],
    'features': ['feature-split-0', 'feature-split-1', 'feature-armed-0', 'feature-armed-1',
                 'datafix2_watch', 'moverfix', 'wave14_order', 'clientcompat-multi-tracking',
                 'clientcompat-multi-controls', 'wb_rule_units', 'wbland_units',
                 'storage_units', 'bugs5', 'atomfix6_units', 'ring_unit', 'filter_unit', 'wait_units',
                 'asan_batteries', 'script_bounds', 'scriptfix', 'scriptfix2', 'lualibs']
        + [f'multifix-{m}-{e}' for m in ('1s', '2s') for e in ('uring', 'epoll')]
        + [f'multidb-{m}-{r}-{a}' for m in ('1s', '2s') for r in (0, 1) for a in (0, 1)],
    'persistence': '''snapshot-epoll snapshot-uring snapfix_shutdown snapfix_bgsave_script
        snapfix_bgsave_exec snapfix2_tables aof-epoll aof-uring aof_frame aoforder dump_restore
        persistfmt persistfmt_aof_error persistfix2_lastsave persistfix2_shutdown
        persistfix2_commands persistfix2_errors persistfix_units flushfix2 flushfix3
        notify_aof rootcore-waitaof serverfix_waitaof climonfix'''.split(),
    'placement': '''flip fliplisten flipfix5 flipfix6 flipctl
        lb-stationary-1s lb-stationary-2s readonly rlfix3_info rlfix3_zc rlcache
        bplus hexpread compat3 notify
        reorder_engagement reorder_sync exbatch_live rldbg wb_mixed slotless rob_portable replyoff zc'''.split()
        + [f'evict-{section}-{mode}-{a}' for section in ('lfu', 'lruclock')
           for mode in ('split', 'armed') for a in (0, 1)]
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
p.add_argument('--binary', type=Path, default=ROOT / 'build/tomokv')
a = p.parse_args()
assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
if a.group == 'atomic' and a.fused:
    # The initial FIFO run overlapped control-object debug compression. Retain
    # that failed latency evidence, then run the complete unchanged job for both
    # arms with no concurrent lane build or artifact processing.
    for arm, binary in [('PRE', ROOT / 'build/pre/tomokv'), ('POST', ROOT / 'build/tomokv')]:
        subprocess.run(['python3', __file__, 'fifo', '--binary', str(binary),
                        '--label', f'fifo-{arm}-idle'], check=False)
if a.group == 'features':
    subprocess.run(['python3', 'tools/atomfix6_compress.py'], check=True)
    subprocess.run(['python3', 'tools/atomfix6_park_pre.py'], check=True)
    with (ROOT / 'docs/atomfix6/gates-test-expanded.log').open('w') as log:
        subprocess.run(['python3', 'tests/gates_test.py'], stdout=log,
                       stderr=subprocess.STDOUT, check=True)
if a.group == 'persistence' and not a.fused:
    subprocess.run(['python3', __file__, 'park', '--label', 'expanded-units-final'], check=False)
if a.group == 'persistence' and a.fused:
    subprocess.run(['python3', __file__, 'order', '--binary', str(ROOT / 'build/pre/tomokv'),
                    '--label', 'wave14-order-PRE'], check=False)
jobs = GROUPS[a.group]
if a.fused:
    # These jobs use txn_proof_boot. Other selected jobs already enumerate
    # their own mode/engine matrices and do not consume GATE_TXN_FUSED.
    fused_jobs = {
        'atomic': ['release_batteries', 'atomic_batteries', 'debug-0', 'debug-1'],
        'persistence': ['snapshot-epoll', 'snapshot-uring', 'aof-epoll',
                        'aof-uring', 'aof_frame', 'dump_restore', 'asan_batteries', 'replyoff', 'zc'],
        'notify': ['notify'],
    }
    if a.group not in fused_jobs:
        p.error('--fused applies only to the generic atomic/persistence boots')
    jobs = fused_jobs[a.group]
label = a.label or f'{a.group}-{a.engine}-' + ('fused' if a.fused else 'default')
out = ROOT / 'docs/atomfix6/proof' / label
out.mkdir(parents=True, exist_ok=True)
env = dict(os.environ, LC_ALL='C', GATE_PROOF_NO_RATES='1',
           CXX='g++ -Wl,--compress-debug-sections=zlib',
           GATE_ONLY_JOBS=' '.join(jobs), GATE_NET_IO=a.engine,
           GATE_PROOF_NET_IO=a.engine, GATE_DIFFER_NET_IO=a.engine,
           GATE_TXN_FUSED=str(int(a.fused)), GATE_LEDGER=str(out / 'ledger.tsv'),
           REDIS74_ROOT='/home/user/Projects/redis',
           GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
           GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli',
           GATE_DIFFER_ORACLE_CORES='74-81')
argv = ['taskset', '-c', '74-86', 'tests/gate.sh', 'full', '--server-cores', '74-81',
        '--load-cores', '82-86', '--load-smt', '', '--server-smt', '',
        '--ports', '21740-21749', '--candidate-binary', str(a.binary.resolve())]
(out / 'request.json').write_text(json.dumps(dict(argv=argv,
    env={k: v for k, v in env.items() if k.startswith(('GATE_', 'REDIS74_', 'LC_ALL'))}), indent=2) + '\n')
with (out / 'gate.log').open('w') as log:
    result = subprocess.run(argv, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
(out / 'exit.json').write_text(json.dumps(dict(rc=result.returncode)) + '\n')
print(label, 'exit', result.returncode, 'log', out / 'gate.log', flush=True)
subprocess.run(['taskset', '-c', '86', 'python3', 'tools/atomfix6_retire.py'], check=True)
if a.group == 'placement':
    subprocess.run(['python3', __file__, 'notify', '--fused',
                    '--label', 'notify-fused'], check=False)
raise SystemExit(result.returncode)
