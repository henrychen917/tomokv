#!/usr/bin/env python3
"""Additional bounded parser coverage; no server, socket, or rate measurement."""
import concurrent.futures, hashlib, json, os, subprocess
from pathlib import Path
from rlfix4_scope import ROOT, OUT, BUILD, trace, save
os.sched_setaffinity(0,set(range(32,48)))
def build(case):
 arm,ns=case;label='admission-'+arm
 r=json.loads((OUT/f'{arm}-{ns}-build.json').read_text())
 dest=BUILD/(label+'-'+ns);dest.mkdir(exist_ok=True)
 cmd=r['compile'].copy();cmd.insert(1,'-DTOMO_RLFIX4_ADMISSION');cmd[-1]=str(dest/'probe.o')
 link=r['link'].copy();link[-1]=str(dest/'probe.o');link[link.index('-o')+1]=str(dest/'probe')
 with (OUT/f'{label}-{ns}-build.log').open('w') as f:
  subprocess.run(cmd,cwd=r.get('cwd',ROOT),stdout=f,stderr=subprocess.STDOUT,check=True)
  subprocess.run(link,cwd=r.get('cwd',ROOT),stdout=f,stderr=subprocess.STDOUT,check=True)
 save(OUT/f'{label}-{ns}-build.json',dict(compile=cmd,link=link,cwd=r.get('cwd',str(ROOT)),
      fixture_sha256=hashlib.sha256((ROOT/'tests/rlfix4_scope.cc').read_bytes()).hexdigest(),
      sha256=hashlib.sha256((dest/'probe').read_bytes()).hexdigest(),server_sha256=r['server_sha256']))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--arms',default='pre,post,pad-a,post-layout');p.add_argument('--build-only',action='store_true');p.add_argument('--trace-only',action='store_true');p.add_argument('--workers',type=int,default=6);a=p.parse_args();arms=a.arms.split(',')
 if not a.trace_only:
  with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(build,[(arm,ns) for arm in arms for ns in ('normal','db0')]))
 if a.build_only:raise SystemExit(0)
 cases=[('admission-'+arm,ns,cmd,mode,n,atomic,-1,route) for arm in arms for ns in ('normal','db0')
        for cmd in ('GET','SET','INCR','MGET','MSET') for mode in ('1s','2s') for n in (1,32)
        for atomic in ((0,1) if cmd=='MSET' else (1,)) for route in ('owner0','owner1')]
 with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:rows=list(pool.map(trace,cases))
 save(OUT/('results-admission-'+a.arms+'.json'),rows)
