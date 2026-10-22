"""Regenerate strict full/hot/command inventories without changing gate policy."""
import gzip,json,re,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'docs/wave4'))
import identity
from target_bodies import bodies
DOC=ROOT/'docs/wave4d/identity';DOC.mkdir(parents=True,exist_ok=True)
refs={arm:identity.inventory(path) for arm,path in identity.REFS.items()}
post=identity.inventory(ROOT/'build/tomokv')
pre=identity.inventory(ROOT/'build/wave4c/tomokv-pre')
rows=identity.compare(post,refs);old={r['name']:r for r in identity.compare(pre,refs)}
command_names={r['name'] for r in json.loads((ROOT/'docs/wave4/identity/command-paths.json').read_text())['bodies']}
summary={}
for label,selected in [('full',rows),('hot',[r for r in rows if r['hot']]),('command_paths',[r for r in rows if r['name'] in command_names])]:
 summary[label]=dict(groups=len(selected),headline=sum(r['equal'] for r in selected),lane=sum(not r['equal'] and bool(r['matches']) for r in selected),residual=sum(not r['matches'] for r in selected),residual_names=[r['name'] for r in selected if not r['matches']])
changed=[r for r in rows if identity.signature(post['groups'].get(r['name'],[]))!=identity.signature(pre['groups'].get(r['name'],[]))]
summary['post']={k:v for k,v in post.items() if k!='groups'}
summary['changed_from_merge']=len(changed)
summary['previous_matches_changed']=[r['name'] for r in changed if old.get(r['name'],{}).get('matches')]
summary['previous_hot_matches_lost']=[r['name'] for r in changed if r['hot'] and old.get(r['name'],{}).get('matches') and not r['matches']]
with gzip.open(DOC/'all-bodies.json.gz','wt') as f:json.dump(rows,f,indent=2)
(DOC/'changed-from-merge.json').write_text(json.dumps(changed,indent=2)+'\n')
(DOC/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(DOC/'command-paths.json').write_text(json.dumps([r for r in rows if r['name'] in command_names],indent=2)+'\n')
print(json.dumps({k:{x:y for x,y in v.items() if x!='residual_names'} if k in ('full','hot','command_paths') else v for k,v in summary.items()},indent=2),flush=True)
# Retain all exact target bodies, including three MGET gather clones and completion.
names={r['name'] for r in rows if 'xshard_execute(' in r['name'] or 'xshard_complete' in r['name']}|command_names
post_bodies=bodies(ROOT/'build/tomokv',names)
with gzip.open(DOC/'command-bodies.json.gz','wt') as f:json.dump(post_bodies,f,indent=2)
