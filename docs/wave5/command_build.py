#!/usr/bin/env python3
import concurrent.futures,hashlib,json,shlex,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'docs/wave5/instructions';OUT.mkdir(exist_ok=True)
def build(arm):
 src=ROOT if arm=='post' else ROOT/'build/wave5/pre-source'
 folder=ROOT/'build/wave5/commands'/arm;folder.mkdir(parents=True,exist_ok=True)
 cmd=['g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(src),'-c',str(ROOT/'docs/wave5/command_scope.cc'),'-o',str(folder/'fixture.o')]
 log=OUT/(arm+'-build.log')
 with log.open('w') as stream:
  rc=subprocess.run(cmd,stdout=stream,stderr=subprocess.STDOUT).returncode
  if rc:return dict(arm=arm,exit=rc,compile=cmd)
  subprocess.run(['objcopy','--redefine-sym','main=wave5_original_main',str(src/'build/db0/src/main.o'),str(folder/'main.o')],check=True)
  recipe=shlex.split(next(s for s in reversed((ROOT/('build/wave5/build-post.log' if arm=='post' else 'build/wave5/build-pre.log')).read_text().splitlines()) if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
  for i,arg in enumerate(recipe):
   if arg=='build/db0/src/main.o':recipe[i]=str(folder/'main.o')
   elif arg.startswith('build/') and arg.endswith('.o'):recipe[i]=str(src/arg)
  recipe[recipe.index('-o')+1]=str(folder/'probe');recipe+= [str(folder/'fixture.o')]
  rc=subprocess.run(recipe,stdout=stream,stderr=subprocess.STDOUT).returncode
  return dict(arm=arm,exit=rc,compile=cmd,link=recipe,production_sha256=hashlib.sha256((src/'build/tomokv').read_bytes()).hexdigest())
with concurrent.futures.ThreadPoolExecutor(2) as p:rows=list(p.map(build,['pre','post']))
(OUT/'builds.json').write_text(json.dumps(rows,indent=2)+'\n')
print(rows)
assert all(r['exit']==0 for r in rows)
