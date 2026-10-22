"""All linked bodies, with the repository's strict instruction normalizer."""
import importlib.util,json,gzip,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('wave_identity',ROOT/'docs/wave4/identity.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
a.OUT=ROOT/'build/fliplisten/identity-cache'
pre=a.inventory(ROOT/'build/tomokv-PRE')
post=a.inventory(ROOT/'build/tomokv')
rows=a.compare(post,{'headline':pre})
changed=[]
for r in rows:
    if r['equal']: continue
    name=r['name']
    if 'fliplisten' in name.lower() or 'FlipListenerState' in name:
        reason='Listener ownership transfer, retained descriptor admission, or cancellation fence.'
    elif any(k in name for k in ('flip_', 'prepare_activation', 'deactivate', 'activate(', '~IoLoop', '~Server')):
        reason='FLIP prepare/install/rollback resource acknowledgements and quota-before-admission barrier.'
    elif any(k in name for k in ('admit_', 'on_accept', 'on_cqe', 'epoll_pass', 'arm_accept', 'run_loop')):
        reason='Existing cold paused/stale/default accept branch delegates to the listener protocol; audit ordinary instruction path.'
    else:
        reason='Compiler/link propagation from cold FLIP implementation; inspect and rederive budgets.'
    r['reason']=reason;changed.append(r)
out=ROOT/'docs/fliplisten/identity';out.mkdir(exist_ok=True)
with gzip.open(out/'all-bodies.json.gz','wt') as f:json.dump(rows,f)
(out/'changed-bodies.json').write_text(json.dumps(changed,indent=2)+'\n')
summary=dict(pre=pre['sha256'],post=post['sha256'],bodies=len(rows),changed=len(changed),
             hot_commands=[r for r in rows if r['command_hot']],
             changed_hot=[r for r in changed if r['hot']])
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('bodies',len(rows),'changed',len(changed),'hot command changed',sum(r['command_hot'] for r in changed))
