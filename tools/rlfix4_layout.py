#!/usr/bin/env python3
"""Offline PRE/POST twins with common bounded text slots; never runs servers.

Release flags and object order are retained. Only affected translation units gain
-ffunction-sections. One shared linker script reserves max(PRE,POST) bytes per
input text section. Padding is unreachable. Counts require separate validation.
"""
import argparse, concurrent.futures, hashlib, json, os, shlex, subprocess
from pathlib import Path
from lbstall_artifacts import Elf
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/rlfix4/layout';OUT.mkdir(parents=True,exist_ok=True)
DOC=ROOT/'docs/rlfix4/layout';DOC.mkdir(parents=True,exist_ok=True)
ARMS={'pre':ROOT/'build/rlfix4/pre-source','post':ROOT}
UNITS=json.loads((ROOT/'docs/rlfix4/changed-code-objects.json').read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,indent=2)+'\n')
def compile_one(case):
 arm,rel=case;src=ARMS[arm];target=src/'build'/rel;dest=OUT/arm/rel;dest.parent.mkdir(parents=True,exist_ok=True)
 receipt=DOC/(arm+'-'+rel.replace('/','_')+'.json')
 if dest.exists() and receipt.exists():
  cached=json.loads(receipt.read_text())
  if cached['original_sha256']==sha(target) and cached['sha256']==sha(dest):return cached
 recipe=subprocess.check_output(['make','-C',str(src),'-n','-B','BUILD_ROOT='+str(src/'build'),str(target)],text=True)
 cmd=next(shlex.split(l) for l in recipe.splitlines() if ' -c ' in l and l.endswith(' -o '+str(target)))
 cmd.insert(1,'-ffunction-sections');cmd[-1]=str(dest)
 with (dest.with_suffix('.log')).open('w') as log:subprocess.run(cmd,cwd=src,stdout=log,stderr=subprocess.STDOUT,check=True)
 result=dict(arm=arm,unit=rel,command=cmd,original_sha256=sha(target),sha256=sha(dest));save(receipt,result)
 return result

def link():
 # Selectors are relative to each arm directory, allowing one identical script.
 slots=[]
 for rel in UNITS:
  elves=[Elf(OUT/a/rel) for a in ARMS]
  names=sorted({n for e in elves for n,s in zip(e.names,e.sections) if s[2]&4})
  for name in names:
   sizes=[];align=[]
   for e in elves:
    matching=[s for n,s in zip(e.names,e.sections) if n==name]
    alignment=max([16]+[s[8] for s in matching])
    # Custom COMDAT sections may repeat the same name within one object.
    sizes.append(sum((s[5]+alignment-1)//alignment*alignment for s in matching))
    align.append(alignment)
   if max(sizes):slots.append(dict(object=rel,section=name,size=max(sizes),alignment=max(16,*align),sizes=dict(zip(ARMS,sizes))))
 lines=['SECTIONS { .text.rlfix4 ALIGN(64) : {']
 for i,s in enumerate(slots):
  lines += [f' . = ALIGN({s["alignment"]}); __rlfix4_slot_{i} = .;',
            f' {s["object"]}({s["section"]})',
            f' . = __rlfix4_slot_{i} + {s["size"]};']
 lines+=[' } } INSERT BEFORE .text;']
 script=OUT/'common.ld';script.write_text('\n'.join(lines)+'\n');save(DOC/'slots.json',slots)
 outputs={}
 for arm,src in ARMS.items():
  # Undo the scope fixture's main rename and appended fixture object.
  receipt=json.loads((ROOT/f'docs/rlfix4/instructions/{arm}-normal-build.json').read_text())
  cmd=receipt['link'][:-1]
  cmd=[str(src/'build/db0/src/main.o') if x.endswith('/original-main.o') else x for x in cmd]
  objects=[]
  for i,x in enumerate(cmd):
   if x.endswith('.o'):
    rel=str(Path(x).relative_to(src/'build'))
    if rel in UNITS:cmd[i]=rel
    objects.append(cmd[i])
  binary=ROOT/('build/tomokv-rlfix4-'+('pad-a' if arm=='pre' else 'post-layout'))
  cmd[cmd.index('-o')+1]=str(binary);cmd+=['-Wl,-T,'+str(script)]
  with (DOC/(arm+'-link.log')).open('w') as log:subprocess.run(cmd,cwd=OUT/arm,stdout=log,stderr=subprocess.STDOUT,check=True)
  outputs[arm]=dict(path=str(binary),sha256=sha(binary),link=cmd,objects=objects)
 save(DOC/'build.json',dict(kind='A: PRE behaviour in POST-layout common text slots',script_sha256=sha(script),arms=outputs))

def probes():
 receipt=json.loads((DOC/'build.json').read_text())
 for arm,src in ARMS.items():
  label='pad-a' if arm=='pre' else 'post-layout'
  for ns in ('normal','db0'):
   cwd=OUT/(arm+'-probe-'+ns);cwd.mkdir(exist_ok=True)
   dest=ROOT/'build/rlfix4/commands'/(label+'-'+ns);dest.mkdir(exist_ok=True)
   for rel in UNITS:
    path=cwd/rel;path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() or path.is_symlink():path.unlink()
    if rel=='db0/src/main.o':
     subprocess.run(['objcopy','--redefine-sym','main=execfair_original_main',str(OUT/arm/rel),str(path)],check=True)
    else:path.symlink_to(OUT/arm/rel)
   flags=['g++','-std=c++20','-O2','-g','-march=native','-pthread','-DTOMO_JEMALLOC','-I'+str(src)]
   if ns=='db0':flags+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0']
   compile=flags+['-c',str(ROOT/'tests/rlfix4_scope.cc'),'-o',str(dest/'probe.o')]
   cmd=receipt['arms'][arm]['link'].copy();cmd[cmd.index('-o')+1]=str(dest/'probe');cmd+=[str(dest/'probe.o')]
   with (DOC/(label+'-'+ns+'-probe.log')).open('w') as log:
    subprocess.run(compile,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
    subprocess.run(cmd,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
   save(ROOT/f'docs/rlfix4/instructions/{label}-{ns}-build.json',dict(compile=compile,link=cmd,cwd=str(cwd),sha256=sha(dest/'probe'),fixture_sha256=sha(ROOT/'tests/rlfix4_scope.cc'),server_sha256=receipt['arms'][arm]['sha256']))

def audit():
 from collections import defaultdict
 def functions(e):
  v=defaultdict(list)
  for s in e.symbols:
   if s['info']&15==2 and 0<s['sec']<len(e.sections) and e.sections[s['sec']][2]&4:v[s['name']].append(s['value'])
  return {k:sorted(v) for k,v in v.items()}
 sections=lambda e:{n:list(s[2:6])+[s[8]] for n,s in zip(e.names,e.sections) if s[2]&4}
 a,b=(Elf(ROOT/('build/tomokv-rlfix4-'+x)) for x in ('pad-a','post-layout'))
 x,y=functions(a),functions(b)
 assert x==y,'function entry addresses differ'
 assert sections(a)==sections(b),'executable section layout differs'
 # The comparator must reject a changed entry, without executing any bad image.
 broken={k:v.copy() for k,v in y.items()};name=next(iter(broken));broken[name][0]+=1
 assert x!=broken
 save(DOC/'addresses.json',dict(function_count=len(x),all_function_entries_equal=True,executable_sections_equal=True,sections=sections(a),negative_control='one entry address changed: rejected',sha256={'pad-a':sha(a.path),'post-layout':sha(b.path)}))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=4);p.add_argument('--link-only',action='store_true');p.add_argument('--probes-only',action='store_true');a=p.parse_args()
 os.sched_setaffinity(0,set(range(32,48)))
 if not a.link_only and not a.probes_only:
  with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:list(pool.map(compile_one,[(arm,r) for arm in ARMS for r in UNITS]))
 if not a.probes_only:link()
 audit()
 probes()
