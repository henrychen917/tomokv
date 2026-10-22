"""Classify strict propagation without relaxing the identity verdict."""
import collections,difflib,gzip,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'docs/wave4'))
import identity
from target_bodies import bodies
DOC=ROOT/'docs/wave4d/identity'
rows=json.loads((DOC/'changed-from-merge.json').read_text())
names={r['name'] for r in rows}
a=bodies(ROOT/'build/wave4c/tomokv-pre',names)
b=bodies(ROOT/'build/tomokv',names)
refs={arm:identity.inventory(path) for arm,path in identity.REFS.items()}
old={r['name']:r for r in identity.compare(identity.inventory(ROOT/'build/wave4c/tomokv-pre'),refs)}
out=[];diffs={}
for row in rows:
 name=row['name'];aa=a.get(name,[]);bb=b.get(name,[])
 enc_equal=[v['encodings'] for v in aa]==[v['encodings'] for v in bb]
 changes=list(difflib.unified_diff([s for v in aa for s in v['ins']],[s for v in bb for s in v['ins']],fromfile='merge',tofile='post',n=2))
 kind='new-or-removed-group' if not aa or not bb else ('same-encoding-reference-only' if enc_equal else 'instruction-encoding-change')
 out.append(dict(name=name,kind=kind,hot=row['hot'],old_matches=old.get(name,{}).get('matches',[]),post_matches=row['matches'],old_sizes=[v['size'] for v in aa],post_sizes=[v['size'] for v in bb]))
 diffs[name]=changes
summary=dict(changed=len(out),kinds=dict(collections.Counter(r['kind'] for r in out)),new_residuals=[r for r in out if r['old_matches'] and not r['post_matches']],real_code_changes=[r for r in out if r['kind']!='same-encoding-reference-only'])
(DOC/'propagation.json').write_text(json.dumps(dict(summary=summary,bodies=out),indent=2)+'\n')
with gzip.open(DOC/'propagation-diffs.json.gz','wt') as f:json.dump(diffs,f,indent=2)
print(json.dumps({k:v for k,v in summary.items() if k not in ('new_residuals','real_code_changes')},indent=2),flush=True)
print('new residual kinds',dict(collections.Counter(r['kind'] for r in summary['new_residuals'])),flush=True)
for r in summary['real_code_changes']:print(r['old_sizes'],r['post_sizes'],r['name'],flush=True)
