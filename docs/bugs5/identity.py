"""All linked bodies, with the repository's strict instruction normalizer."""
import importlib.util,json,gzip,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('wave_identity',ROOT/'docs/wave4/identity.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)
a.OUT=ROOT/'build/bugs5/identity-cache'
pre=a.inventory(ROOT/'build/tomokv-PRE')
post=a.inventory(ROOT/'build/tomokv')
rows=a.compare(post,{'headline':pre})
changed=[]
for r in rows:
    if r['equal']:continue
    name=r['name']
    if 'slowlog' in name.lower() or 'Slowlog' in name or 'directory' in name:
        reason='SV4.3 immutable identity capture, storage, or shared ownership lifetime.'
    elif 'cmd_hscan' in name:
        reason='CD4.2 compact full-iteration reply.'
    elif 'ExLoopT' in name and 'init(' in name:
        reason='RL4.1 nonzero sampler seed; no loop layout change.'
    else:
        reason='Compiler/layout propagation from HSCAN, cold slowlog capture/signature, or LFU seed changes; merit input.'
    r['reason']=reason;changed.append(r)
out=ROOT/'docs/bugs5/identity';out.mkdir(exist_ok=True)
with gzip.open(out/'all-bodies.json.gz','wt') as f:json.dump(rows,f)
(out/'changed-bodies.json').write_text(json.dumps(changed,indent=2)+'\n')
summary=dict(pre=pre['sha256'],post=post['sha256'],bodies=len(rows),changed=len(changed),
             hot_commands=[r for r in rows if r['command_hot']],
             changed_hot=[r for r in changed if r['hot']])
(out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print('bodies',len(rows),'changed',len(changed),'hot command changed',sum(r['command_hot'] for r in changed))
