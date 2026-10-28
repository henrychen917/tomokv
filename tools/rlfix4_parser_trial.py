#!/usr/bin/env python3
"""Compile isolated parser alternatives against frozen surrounding POST objects."""
import argparse, concurrent.futures, hashlib, json, os, shlex, shutil, subprocess
from pathlib import Path
from rlfix4_scope import ROOT, OUT, BUILD, trace, save
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('--original-aof',action='store_true');p.add_argument('--inline-room',action='store_true');p.add_argument('--normal-cmd-name',action='store_true');a=p.parse_args()
os.sched_setaffinity(0,set(range(32,48)))
src=ROOT/'build/rlfix4'/a.name;src.mkdir(exist_ok=True)
shutil.copytree(ROOT/'src',src/'src',dirs_exist_ok=True);shutil.copy2(ROOT/'Makefile',src/'Makefile')
if not (src/'third_party').exists():(src/'third_party').symlink_to(ROOT/'third_party')
for path in [src/'src/core/io_loop.h',src/'src/core/reorder.cc']:
 s=path.read_text()
 if a.original_aof:
  old='if ((!Fused || !read_local_eligible) &&\n                __builtin_expect(srv_->aof().failed(), false) && srv_->aof().deny_command(*op))'
  # The generated body is indented four columns less.
  if old not in s:old=old.replace('\n                ','\n            ')
  assert old in s;s=s.replace(old,'if (__builtin_expect(srv_->aof().failed(), false) && srv_->aof().deny_command(*op))')
 if a.normal_cmd_name:s=s.replace('command_lookup(op->arg(0))','command_lookup(kSingleDatabase ? op->arg(0) : op->cmd_name())')
 path.write_text(s)
if a.inline_room:
 path=src/'src/core/ex_loop.h';s=path.read_text();s=s.replace('    bool local_read_lane_has_room(', '    __attribute__((always_inline)) bool local_read_lane_has_room(');path.write_text(s)
units=[x+'/'+y for x in ('src','db0/src') for y in ('main.o','core/genthread.o','core/reorder.o')]
def compile_one(rel):
 target=ROOT/'build'/rel;dest=src/'build'/rel;dest.parent.mkdir(parents=True,exist_ok=True)
 recipe=subprocess.check_output(['make','-n','-B',str(target.relative_to(ROOT))],cwd=ROOT,text=True)
 cmd=next(shlex.split(l) for l in recipe.splitlines() if ' -c ' in l and l.endswith(' -o '+str(target.relative_to(ROOT))))
 cmd[-1]=str(dest)
 with dest.with_suffix('.log').open('w') as f:subprocess.run(cmd,cwd=src,stdout=f,stderr=subprocess.STDOUT,check=True)
 return dict(unit=rel,command=cmd,sha256=hashlib.sha256(dest.read_bytes()).hexdigest())
with concurrent.futures.ThreadPoolExecutor(6) as pool:receipts=list(pool.map(compile_one,units))
save(OUT/(a.name+'-units.json'),receipts)
for admission in (False,True):
 for ns in ('normal','db0'):
  label=('admission-' if admission else '')+a.name;dest=BUILD/(label+'-'+ns);dest.mkdir(exist_ok=True)
  r=json.loads((OUT/f'post-{ns}-build.json').read_text());cmd=r['compile'].copy()
  cmd=[x if not x.startswith('-I') else '-I'+str(src) for x in cmd];cmd[-1]=str(dest/'probe.o')
  if admission:cmd.insert(1,'-DTOMO_RLFIX4_ADMISSION')
  rename=['objcopy','--redefine-sym','main=execfair_original_main',str(src/'build/db0/src/main.o'),str(dest/'original-main.o')]
  link=r['link'].copy();link[-1]=str(dest/'probe.o');link[link.index('-o')+1]=str(dest/'probe')
  for i,x in enumerate(link):
   if x.endswith('/original-main.o'):link[i]=str(dest/'original-main.o')
   elif x.startswith(str(ROOT/'build')+'/') and str(Path(x).relative_to(ROOT/'build')) in units:link[i]=str(src/'build'/Path(x).relative_to(ROOT/'build'))
  with (OUT/f'{label}-{ns}-build.log').open('w') as f:
   for c in (cmd,rename,link):subprocess.run(c,cwd=src,stdout=f,stderr=subprocess.STDOUT,check=True)
  save(OUT/f'{label}-{ns}-build.json',dict(compile=cmd,rename=rename,link=link,sha256=hashlib.sha256((dest/'probe').read_bytes()).hexdigest()))
cases=[(a.name,ns,'GET','1s',n,1,-1,route) for ns in ('normal','db0') for n in (1,32) for route in ('parse','parsemix','r7parse','r7mix')]
cases+=[('admission-'+a.name,ns,cmd,mode,n,atomic,-1,route) for ns in ('normal','db0') for cmd in ('GET','SET','INCR','MGET','MSET') for mode in ('1s','2s') for n in (1,32) for atomic in ((0,1) if cmd=='MSET' else (1,)) for route in ('owner0','owner1')]
with concurrent.futures.ThreadPoolExecutor(8) as pool:rows=list(pool.map(trace,cases))
save(OUT/('results-'+a.name+'.json'),rows)
