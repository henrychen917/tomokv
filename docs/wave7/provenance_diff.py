#!/usr/bin/env python3
import concurrent.futures,difflib,gzip,json
from pathlib import Path
import identity
ROOT=identity.ROOT;DOC=ROOT/'docs/wave7/instructions';provenance=json.load(open(DOC/'provenance.json'))
names={r['name'] for a in ('pre','post') for ns in ('normal','db0') for r in provenance[a+'-'+ns] if not r['production_equal']}
paths={k:v['path'] for k,v in provenance['links'].items() if k!='headline'}
def one(item):
 key,path=item;dest=ROOT/'build/wave7/provenance-diffs'/key;dest.mkdir(parents=True,exist_ok=True)
 b=identity.audit.Binary(path,dest,literal_pools=True)
 data={name:b.groups.get(name,[]) for name in names}
 for p in dest.glob('*.objdump'):p.unlink()
 return key,data
with concurrent.futures.ProcessPoolExecutor(3) as p:data=dict(p.map(one,paths.items()))
with gzip.open(DOC/'provenance-bodies.json.gz','wt') as f:json.dump(data,f)
for arm in ('pre','post'):
 for ns in ('normal','db0'):
  for row in provenance[arm+'-'+ns]:
   if row['production_equal']:continue
   n=row['name'];a=data[arm+'-production'][n][0];b=next(b for b in data[arm+'-'+ns][n] if hex(b['addr'])==row['address'])
   diff='\n'.join(difflib.unified_diff(a['ins'],b['ins'],fromfile='production',tofile='probe'))
   print(arm,ns,n);print(diff[:12000],flush=True)
