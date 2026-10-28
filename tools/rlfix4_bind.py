#!/usr/bin/env python3
"""Bind every counted body to a same-arm linked production server body."""
import concurrent.futures, gzip, json, os
from pathlib import Path
from rlfix4_identity import inventory
ROOT=Path(__file__).resolve().parents[1]
DOC=ROOT/'docs/rlfix4';INS=DOC/'instructions'
ARMS={'anchor':'anchor','wave6':'wave6','wave7':'wave7','pre':'pre',
      'preparse':'pre','post':'post','pad-a':'pad-a','post-layout':'post-layout'}
def run(arm):
 server=inventory(ROOT/('build/tomokv-rlfix4-'+ARMS[arm]))
 with gzip.open(DOC/('identity/rebuilt-'+arm+'.json.gz'),'wt') as out:json.dump(server,out)
 rows=[]
 for ns in ('normal','db0'):
  probe=inventory(ROOT/f'build/rlfix4/commands/{arm}-{ns}/probe')
  wanted={}
  for f in INS.glob(arm+'-'+ns+'-*.json'):
   trace=json.loads(f.read_text())
   if 'bodies' not in trace or trace['binary_sha256']!=probe['sha256']:continue
   for ident,count in trace['bodies'].items():wanted[ident]=wanted.get(ident,0)+count
  assert wanted,(arm,ns,'no current hash-bound traces')
  for ident,count in sorted(wanted.items()):
   address,name=ident.split(' ',1)
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
 import sys
 os.sched_setaffinity(0,set(range(32,48)))
 with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(run,sys.argv[1:] or ARMS))
 if not all(r['pass_'] for r in results):raise SystemExit(1)
