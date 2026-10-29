#!/usr/bin/env python3
"""Bind every counted body to a same-arm linked production server body."""
import concurrent.futures, gzip, json, os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"tools"))
from rlfix4_identity import inventory
import rlfix4_identity
from wave10_normalize import install
install(rlfix4_identity.audit)
rlfix4_identity.OUT = Path(__file__).resolve().parents[2] / 'build/wave10/binding-resolved'
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave10';INS=DOC/'instructions'
import sys
sys.path.insert(0,str(ROOT/'tools'))
SERVER=Path(sys.argv[2]).resolve()
def run(arm):
 server=inventory(SERVER)
 with gzip.open(DOC/('binding-server-'+arm+'.json.gz'),'wt') as out:json.dump(server,out)
 rows=[]
 for ns in ('normal','db0'):
  probe=inventory(ROOT/f'build/wave10/scopes/{arm}-{ns}/probe')
  wanted={};sites={}
  for f in (INS/arm).glob(arm+'-'+ns+'-*.json'):
   trace=json.loads(f.read_text())
   if 'bodies' not in trace or trace['binary_sha256']!=probe['sha256']:continue
   for ident,count in trace['bodies'].items():wanted[ident]=wanted.get(ident,0)+count
   with gzip.open(str(f)+'.sites.gz','rt') as stream:site_record=json.load(stream)
   for address,count in site_record['sites'].items():sites[int(address,16)]=sites.get(int(address,16),0)+count
  assert wanted,(arm,ns,'no current hash-bound traces')
  for ident,count in sorted(wanted.items()):
   address,name=ident.split(' ',1)
   if name.endswith('[asm .rlfence]'):
    label,actual=next((n,r) for n,r in probe['assembly'].items() if int(r['address'],16)==int(address,16))
    other=server['assembly'].get(label,{})
    offsets=[hex(pc-int(address,16)) for pc in sites if int(address,16)<=pc<int(address,16)+actual['size']]
    passed=bool(offsets) and all(actual['instructions'].get(o)==other.get('instructions',{}).get(o) for o in offsets)
    rows.append(dict(arm=arm,namespace=ns,name=name,address=address,count=count,assembly_region=label,offsets=offsets,pass_=passed))
    continue
   candidates=probe['groups'].get(name,[])
   actual=[r for r in candidates if int(r['address'],16)==int(address,16)]
   matches=[r for r in server['groups'].get(name,[]) if actual and r['digest']==actual[0]['digest']]
   rows.append(dict(arm=arm,namespace=ns,name=name,address=address,count=count,
       matches=matches,probe=actual,pass_=bool(actual and matches)))
 result=dict(server_sha256=server['sha256'],bodies=rows,pass_=all(r['pass_'] for r in rows))
 (DOC/('binding-'+arm+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 print(arm,len(rows),'mismatches',sum(not r['pass_'] for r in rows),flush=True)
 return result
if __name__=='__main__':
 assert os.sched_getaffinity(0) <= set(range(64,96))
 result=run(sys.argv[1])
 raise SystemExit(0 if result['pass_'] else 1)
