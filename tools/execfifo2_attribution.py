#!/usr/bin/env python3
"""Account for every measured EXEC instruction delta; no residual bucket."""
from collections import defaultdict
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]/'docs/execfifo2'
def classify(name):
    if 'service_txn_boundary<' in name:return 'H3 boundary', 'C1 markless/serve check and owner-shard boundary scan'
    if 'service_multi_chain<' in name:return 'Runnable drain', 'C1 recursion guard and owner-local runnable drain'
    if 'service_multi_retries<' in name or 'queue_fast_multi_retry(' in name:return 'Retry queue', 'C1 queue fields, boundary service and nonrecursive drain scheduling'
    if 'ExLoopT<' in name:return 'Owner dispatch', 'C1 ingress/final boundary calls, runnable promotion callback, and writer-promoter context'
    if 'multi_local_runnable(' in name:return 'Local event promotion', 'C1 scans participant slots and calls the owner-local promoter; null-promoter guard in direct scope'
    if 'multi_execute_task(' in name:return 'EXEC state machine', 'C1 event call sites, finish_command result and their compiler register allocation'
    if 'watch_key_ready' in name:return 'Unchanged non-FIFO predicate', 'Old watch_key_ready body becomes watch_key_ready_impl<false>; pair the renamed functions before interpreting the delta'
    if 'watch_promote_unit_waiter(' in name:return 'FIFO hand-off', 'B adds an eligible stamped plain-writer promotion check at unit completion'
    if 'allocate_participant_state(' in name:return 'Retry node initialization', 'C1 larger owner retry nodes and markless-kind initialization'
    if 'txn_add_claim(' in name or 'database_owned_key' in name:return 'Claim construction codegen', 'Source-equivalent claim/key construction is outlined differently in the enlarged xshard unit; pair caller and callee'
    if 'vector<' in name and 'TxnClaim' in name:return 'Claim size', 'B EXEC-filter links enlarge embedded TxnWaiter copies in TxnClaim vector growth'
    if 'MultiExecState::~MultiExecState' in name:return 'Retry node destruction', 'C1 retry-node stride/destruction codegen'
    if 'FlatStore::atomic_collapse(' in name or 'FlatStore::snapshot_prepare_write(' in name:return 'Store codegen spillover', 'Unchanged FlatStore source has different emitted COMDAT code from the changed translation unit; this is residual compiler cost, not FIFO work'
    raise AssertionError('unattributed function: '+name)
all_rows=[]
for kind in ('exec','owner'):
    rows=json.loads((ROOT/kind/'comparison.json').read_text())
    assert len(rows)==48
    for row in rows:
        assert sum(row['functions'].values())==row['delta']
        totals=defaultdict(int);functions=[]
        for name,delta in row['functions'].items():
            category,reason=classify(name);totals[category]+=delta
            functions.append(dict(function=name,delta=delta,category=category,reason=reason))
        assert sum(totals.values())==row['delta']
        all_rows.append({k:v for k,v in row.items() if k!='functions'}|dict(scope=kind,categories=dict(totals),functions=functions))
(ROOT/'attribution.json').write_text(json.dumps(all_rows,indent=2)+'\n')
print('Every function delta accounted for in',len(all_rows),'PRE/POST EXEC comparisons')
