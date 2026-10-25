#!/usr/bin/env python3
import json,sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import identity
ROOT=identity.ROOT;sys.path.insert(0,str(ROOT/'tests'));import r7shadow_noop as r7
DOC=ROOT/'docs/wave7/r7-inventory';DOC.mkdir(exist_ok=True)
def one(pair):
 arm,path=pair;out=DOC/(arm+'.json')
 if out.exists():
  cached=json.loads(out.read_text())
  if cached['sha256']==identity.audit.digest(path):return cached
 dest=ROOT/'build/wave7/r7-inventory'/arm;dest.mkdir(parents=True,exist_ok=True)
 b=identity.audit.Binary(path,dest,literal_pools=True);excluded=r7.off_roles(b)
 names={name:len(bodies) for name,bodies in b.groups.items() if identity.audit.category(name)}
 counts=Counter()
 for n,c in names.items():counts['tomo_db0' if 'tomo_db0::' in n else 'tomo']+=c
 rows=dict(arm=arm,path=str(path),sha256=b.sha256,counts=dict(counts),names=names,excluded=excluded)
 out.write_text(json.dumps(rows,indent=2)+'\n')
 for f in dest.glob('*.objdump'):f.unlink()
 print(arm,dict(counts),flush=True);return rows
with ProcessPoolExecutor(3) as p:rows=list(p.map(one,[*identity.REFS.items(),('merged',ROOT/'build/tomokv')]))
(DOC/'summary.json').write_text(json.dumps([dict(arm=r['arm'],counts=r['counts'],sha256=r['sha256']) for r in rows],indent=2)+'\n')
a=rows[0]['names'];b=rows[-1]['names'];delta={n:[a.get(n,0),b.get(n,0)] for n in a.keys()|b.keys() if a.get(n,0)!=b.get(n,0)}
(DOC/'merged-delta.json').write_text(json.dumps(delta,indent=2)+'\n');print(json.dumps(delta,indent=2))
