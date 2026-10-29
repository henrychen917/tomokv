#!/usr/bin/env python3
"""Re-derive the split-local TU budget using the bounded admission census."""
import concurrent.futures,hashlib,json,os,subprocess
from pathlib import Path
from rlfix4_scope import ROOT,OUT,BUILD,trace,save
os.sched_setaffinity(0,set(range(32,48)))
BASE='parser-fused-metadata';SRC=ROOT/'build/rlfix4'/BASE
RECEIPT=json.loads((OUT/(BASE+'-units.json')).read_text())
ORIGINAL=next(r for r in RECEIPT if r['unit']=='src/core/rl2s.o')
def one(delta):
 label='rl2s-budget-'+str(delta);dest=BUILD/(label+'-normal');dest.mkdir(exist_ok=True)
 budget=164621+delta;cmd=[('large-unit-insns='+str(budget)) if x.startswith('large-unit-insns=') else x for x in ORIGINAL['command']]
 cmd[-1]=str(dest/'rl2s.o')
 with (dest/'build.log').open('w') as f:subprocess.run(cmd,cwd=SRC,stdout=f,stderr=subprocess.STDOUT,check=True)
 receipt=json.loads((OUT/('admission-'+BASE+'-normal-build.json')).read_text());link=receipt['link'].copy()
 link=[str(dest/'rl2s.o') if x==str(SRC/'build/src/core/rl2s.o') else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
 with (dest/'build.log').open('a') as f:subprocess.run(link,cwd=SRC,stdout=f,stderr=subprocess.STDOUT,check=True)
 save(OUT/(label+'-build.json'),dict(budget=budget,compile=cmd,link=link,sha256=hashlib.sha256((dest/'probe').read_bytes()).hexdigest(),object_sha256=hashlib.sha256((dest/'rl2s.o').read_bytes()).hexdigest()))
 return label
if __name__=='__main__':
 import sys
 deltas=list(map(int,sys.argv[1:])) or [-64,-32,-16,16,32,64,128,256]
 with concurrent.futures.ThreadPoolExecutor(8) as pool:labels=list(pool.map(one,deltas))
 cases=[(label,'normal',cmd,'2s',n,at,-1,route) for label in labels for cmd in ('GET','SET','INCR','MGET','MSET') for n in (1,32) for at in ((0,1) if cmd=='MSET' else (1,)) for route in ('owner0','owner1')]
 with concurrent.futures.ThreadPoolExecutor(8) as pool:rows=list(pool.map(trace,cases))
 save(OUT/('results-rl2s-budgets-'+','.join(map(str,deltas))+'.json'),rows)
