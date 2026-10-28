#!/usr/bin/env python3
"""Record every residual body's call sites against every lane and headline."""
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
import difflib,gzip,hashlib,json,os,re,subprocess
from pathlib import Path
import identity
ROOT=identity.ROOT;DOC=ROOT/os.getenv('WAVE9_CALLS_DOC','docs/wave9/callsites');DOC.mkdir(exist_ok=True)
rows=json.loads((ROOT/'docs/wave9/identity/changed-bodies.json').read_text()); residual=[r for r in rows if not r['matches']];wanted={r['name'] for r in residual}
def get(pair):
 arm,path=pair;out=DOC/(arm+'.json.gz')
 key=dict(sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),names=sorted(wanted))
 stamp=DOC/(arm+'-cache-key.json')
 # Frozen references can reuse a superset from the earlier complete audit.
 if not out.exists():
  for prior in ('callsites-budgets','callsites-initial'):
   old=ROOT/'docs/wave9'/prior/(arm+'.json.gz')
   oldkey=ROOT/'docs/wave9'/prior/(arm+'-cache-key.json')
   if old.exists() and oldkey.exists():
    previous=json.loads(oldkey.read_text())
    if previous['sha256']==key['sha256'] and wanted<=set(previous['names']):
     with gzip.open(old,'rt') as f:cached=json.load(f)
     with gzip.open(out,'wt') as f:json.dump({n:cached[n] for n in wanted},f)
     stamp.write_text(json.dumps(key,indent=2)+'\n');break
 if out.exists() and stamp.exists() and json.loads(stamp.read_text())==key:
  with gzip.open(out,'rt') as f:cached=json.load(f)
  for bodies in cached.values():
   for b in bodies:b['calls']=[m[1] for ins in b['ins'] if (m:=re.search(r'\] ((?:bnd )?(?:call|jmp)\s+(?!<\+).*)',ins))]
  with gzip.open(out,'wt') as f:json.dump(cached,f)
  return arm,cached
 d=ROOT/'build/wave9/callsites'/arm;d.mkdir(parents=True,exist_ok=True)
 b=identity.audit.Binary(path,d,literal_pools=True)
 rows={n:[dict(ins=f['ins'],encodings=f['encodings'],calls=[m[1] for ins in f['ins'] if (m:=re.search(r'\] ((?:bnd )?(?:call|jmp)\s+(?!<\+).*)',ins))]) for f in sorted(b.groups.get(n,[]),key=lambda x:x['addr'])] for n in wanted}
 with gzip.open(out,'wt') as f:json.dump(rows,f)
 stamp.write_text(json.dumps(key,indent=2)+'\n')
 for p in d.glob('*.objdump'):p.unlink()
 return arm,rows
with ProcessPoolExecutor(max_workers=3) as pool:inv=dict(pool.map(get,[*identity.REFS.items(),('post',str(ROOT/os.getenv('WAVE9_CALLS_BINARY','build/tomokv')))]))
rows=[]
for r in residual:
 name=r['name'];post=inv['post'][name];refs={arm:inv[arm][name] for arm in identity.REFS}
 # Each changed body's parentage is explicit. All references retained, even
 # when the merged body contains more than one lane's changes.
 comparisons={}
 for arm,bodies in refs.items():
  before=Counter(c for f in bodies for c in f['calls']);after=Counter(c for f in post for c in f['calls'])
  comparisons[arm]=dict(added=dict(after-before),removed=dict(before-after),same=before==after,clones_before=len(bodies),clones_after=len(post))
 row=dict(r,callsites=comparisons);rows.append(row)
 if post:
  arm=r['changed_lanes'][0] if len(r['changed_lanes']) == 1 else 'headline'
  fn=DOC/('diff-'+str(len(rows))+'.txt')
  a=['CLONE '+str(i)+' '+s for i,f in enumerate(refs[arm]) for s in f['ins']];b=['CLONE '+str(i)+' '+s for i,f in enumerate(post) for s in f['ins']]
  fn.write_text(name+'\n'+'\n'.join(difflib.unified_diff(a,b,fromfile=arm,tofile='post'))+'\n');row['diff']=str(fn.relative_to(ROOT))
(DOC/'summary.json').write_text(json.dumps(rows,indent=2)+'\n')
for r in rows:
 if r['command_hot']:
  arm=r['changed_lanes'][0] if len(r['changed_lanes']) == 1 else 'headline';c=r['callsites'][arm]
  if not c['same']:print(r['name'],arm,json.dumps(c),r.get('diff'),flush=True)
