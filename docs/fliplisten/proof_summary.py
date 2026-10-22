"""Summarize the lane's own final receipts without converting a partial gate to green."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];DOC=ROOT/'docs/fliplisten'
arms=json.loads((DOC/'arms.json').read_text())['arms']
post_sha=arms['POST']['sha256']
labels=['pre-scored-listeners','pre-all-flip-uring','pre-all-flip-epoll','post-all-flip-uring',
        'pre-reorder-sync','post-epoch-uring','post-epoch-epoll']
rows=[]
for label in labels:
 p=DOC/'proof'/label
 ledger=(p/'ledger.partial').read_text().splitlines()
 rows.append(dict(label=label,returncode=int((p/'returncode').read_text()),
    ok=sum(x.startswith('ok\t') for x in ledger),
    failed=[x.split('\t',2)[2] for x in ledger if x.startswith('FAIL\t')],
    command=json.loads((p/'command.json').read_text())))
matrix={}
for label in ['pre-scored-listeners','post-epoch-uring']:
 r=json.loads((DOC/'gate-receipts'/(label+'.json')).read_text())
 assert len(r['legs'])==16,(label,len(r['legs']))
 matrix[label]=r['legs']
 if label.startswith('post-'):
  assert all(x.get('passed') and x['sha256']==post_sha for x in r['legs'])
stale=[json.loads(p.read_text()) for p in sorted((DOC/'stale').glob('a*.json'))]
for atomic in (0,1):
 r=[x for x in stale if x['atomic']==atomic]
 assert r and any(x['positive_stale'] for x in r)
 assert all(x['sha256']==post_sha and x['counts']['arrived']==x['counts']['served']==x['unique_ids']==x['accepted_delta'] and not x['errors'] for x in r)
fresh=json.loads((DOC/'freshness.json').read_text())
assert all(x['returncode']==0 for x in fresh['targets'])
repro=json.loads((DOC/'post-controls/results.json').read_text())
assert len(repro)==20 and all(x['new_connections']==["b'PONG'"]*24 for x in repro if 'new_connections' in x)
assert json.loads((DOC/'post-controls/binary.json').read_text())['sha256']==post_sha
soak=json.loads((DOC/'soak/results.json').read_text())
assert len(soak)==2 and all(x['seconds']>=120 and x['server_returncode']==0 for x in soak)
for row in soak:
 assert json.loads((DOC/'soak'/row['engine']/'command.json').read_text())['sha256']==post_sha
differential=json.loads((DOC/'differ/results.json').read_text())
assert {(r['engine'],r['geometry']) for r in differential}=={(e,g) for e in ('uring','epoll') for g in ('split','armed-fused')}
for row in differential:
 command=json.loads((DOC/'differ'/(row['engine']+'-'+row['geometry'])/'command.json').read_text())
 assert command['sha256']==post_sha
result=dict(gate_scope='Partial jobs only; no full-gate or performance receipt',
 gates=rows,arrival_matrix=matrix,stale_accepts=stale,soak=soak,
 differential=differential,
 gates_test_returncode=int((DOC/'gates-test-final.returncode').read_text()),
 fresh_targets=len(fresh['targets']),post_reproduction_cases=len(repro),
 arms=arms)
(DOC/'proof-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(gates=[dict(label=x['label'],ok=x['ok'],failed=x['failed']) for x in rows],
    differential=result['differential'],fresh_targets=result['fresh_targets'],
    gates_test_returncode=result['gates_test_returncode']),indent=2))
