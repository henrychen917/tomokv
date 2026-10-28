#!/usr/bin/env python3
"""Compile-only integration boundaries; retain exact recipes and parser callees."""
import hashlib,json,os,re,shlex,shutil,subprocess,tarfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from lbstall_artifacts import Elf
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/rlfix4/boundaries';OUT.mkdir(exist_ok=True)
SCRATCH=ROOT/'build/rlfix4/boundaries';SCRATCH.mkdir(exist_ok=True)
UNITS=[x+'/'+y for x in ('src','db0/src') for y in ('main.o','core/genthread.o','core/reorder.o')]
REVISIONS=('b01b5a11c^','b01b5a11c','5a9181ac4^','5a9181ac4','e42a75b6e^','e42a75b6e')
def build_one(case):
 source,rel=case;target=source/'build'/rel
 recipe=subprocess.check_output(['make','-C',str(source),'-n','-B','BUILD_ROOT='+str(source/'build'),str(target)],text=True)
 command=next(shlex.split(l) for l in recipe.splitlines() if ' -c ' in l and l.endswith(' -o '+str(target)))
 command=[x if x!='-g' else '-g0' for x in command];target.parent.mkdir(parents=True,exist_ok=True)
 log=OUT/(source.name+'-'+rel.replace('/','_')+'.log')
 with log.open('w') as stream:subprocess.run(command,cwd=source,stdout=stream,stderr=subprocess.STDOUT,check=True)
 elf=Elf(target);symbols=[s for s in elf.symbols if s['info']&15==2 and s['size']]
 demangled=subprocess.check_output(['c++filt'],input='\n'.join(s['name'] for s in symbols),text=True).splitlines()
 rows=[]
 for s,name in zip(symbols,demangled):
  if not any(k in name for k in ('parse_and_dispatch<false, 32u, false>','drain_local_reads_bounded_impl<false>','prepare_local_read(','hash_key(','siphash12','cmd_name()','local_read_lane_has_room','notify_sender(')):continue
  canonical=elf.canonical(s)
  rows.append(dict(name=name,size=s['size'],digest=hashlib.sha256(repr(canonical).encode()).hexdigest(),canary_loads=elf.body(s).count(bytes.fromhex('64 48 8b 04 25 28 00 00 00')),references=[r for r in canonical[1]]))
 result=dict(commit=source.name,unit=rel,command=command,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),bodies=rows)
 (OUT/(source.name+'-'+rel.replace('/','_')+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 return result
if __name__=='__main__':
 os.sched_setaffinity(0,set(range(32,48)));results=[]
 for rev in REVISIONS:
  commit=subprocess.check_output(['git','rev-parse',rev],cwd=ROOT,text=True).strip();source=SCRATCH/commit[:9]
  source.mkdir(exist_ok=True);archive=source/'source.tar'
  with archive.open('wb') as f:subprocess.run(['git','archive',commit,'Makefile','src','third_party','tools','tests'],cwd=ROOT,stdout=f,check=True)
  with tarfile.open(archive) as f:f.extractall(source,filter='data')
  with ThreadPoolExecutor(6) as pool:rows=list(pool.map(build_one,[(source,rel) for rel in UNITS]))
  results.append(dict(revision=rev,commit=commit,units=rows));(OUT/'results.json').write_text(json.dumps(results,indent=2)+'\n')
  shutil.rmtree(source)
  print(rev,'recorded; scratch deleted',flush=True)
