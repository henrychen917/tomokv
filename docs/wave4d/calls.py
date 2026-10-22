#!/usr/bin/env python3
"""Enumerate every linked call/tail site of the ten wave4 command residuals."""
import collections, gzip, json, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'docs/wave4'))
import identity
OUT=ROOT/'build/wave4d/calls'; OUT.mkdir(parents=True,exist_ok=True)
DOC=ROOT/'docs/wave4d'
names=[r['name'] for r in json.loads((ROOT/'docs/wave4c/reference-policy.json').read_text())]
refs=dict(headline=identity.REFS['headline'], moverfix=identity.REFS['moverfix'], merged=str(ROOT/'build/wave4c/tomokv-pre'))
if len(sys.argv)>1: refs['post']=sys.argv[1]
result={}
for arm,path in refs.items():
 cache=OUT/(identity.audit.digest(path)+'.json.gz')
 if cache.exists():
  with gzip.open(cache,'rt') as f: result[arm]=json.load(f)
  continue
 binary=identity.audit.Binary(path,OUT,literal_pools=True)
 rows={}
 for name in names:
  bodies=sorted(binary.groups[name],key=lambda b:b['addr'])
  rows[name]=[]
  for body in bodies:
   sites=[]
   for ins in body['ins']:
    m=re.match(r'([0-9a-f]+) \[ *\d+\] (call|jmp) (.*)', ins)
    if m and not m[3].startswith('<+'): sites.append(dict(offset=m[1],kind=m[2],target=m[3]))
   rows[name].append(dict(address=hex(body['addr']),size=body['size'],calls=sites,ins=body['ins'],encodings=body['encodings']))
 result[arm]=dict(binary=path,sha256=binary.sha256,groups=rows)
 with gzip.open(cache,'wt') as f: json.dump(result[arm],f)
 for p in OUT.glob('*.objdump'): p.unlink()
with gzip.open(DOC/('call-sites'+('-post' if 'post' in refs else '')+'.json.gz'),'wt') as f: json.dump(result,f,indent=2)
summary=[]
for name in names:
 for ref in ('headline','moverfix'):
  for arm in (['merged','post'] if 'post' in refs else ['merged']):
   a=result[ref]['groups'][name]; b=result[arm]['groups'][name]
   counter=lambda bodies: collections.Counter((s['kind'],s['target']) for body in bodies for s in body['calls'])
   ca,cb=counter(a),counter(b)
   row=dict(name=name,reference=ref,candidate=arm,sizes=[[x['size'] for x in a],[x['size'] for x in b]],
            removed=[dict(kind=k[0],target=k[1],count=v) for k,v in (ca-cb).items()],
            added=[dict(kind=k[0],target=k[1],count=v) for k,v in (cb-ca).items()],
            encodings_equal=[x['encodings'] for x in a]==[x['encodings'] for x in b])
   summary.append(row)
   print(json.dumps(row),flush=True)
(DOC/('call-differences'+('-post' if 'post' in refs else '')+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
