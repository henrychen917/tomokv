#!/usr/bin/env python3
"""Compile-only per-unit trials and linked reference scoring; no server or workload."""
from concurrent.futures import ProcessPoolExecutor
import hashlib,json,os,re,shlex,subprocess,sys
from pathlib import Path
import identity
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64,96)))
ROOT=identity.ROOT
ROUND=os.getenv('WAVE9_BUDGET_ROUND','')
OUT=ROOT/('build/wave9/budgets'+ROUND);DOC=ROOT/('docs/wave9/budgets'+ROUND)
PRE=ROOT/'build/wave9/pre-source'
sys.path.insert(0,str(ROOT/'tools'))
from ccfix_audit import audit

def budgets(path):
 return {m[1]:int(m[2]) for m in re.finditer(r'^\$\(BUILD_ROOT\)/([^:\n]+):[^\n]*large-unit-insns=(\d+)',path.read_text(),re.M)}

def recipe(arm,obj):
 source=PRE if arm == 'pre' else ROOT
 text=subprocess.check_output(['make','-B','-n','build/'+obj],cwd=source,text=True)
 return shlex.split(next(s for s in reversed(text.splitlines()) if s.startswith('g++ ') and s.endswith(' -o build/'+obj)))

def trial(job):
 arm,obj,value=job['arm'],job['object'],job['budget']
 tag=obj.replace('/','_')+'-'+arm+'-'+str(value)
 receipt=OUT/(tag+'.json');dest=OUT/(tag+'.o')
 if receipt.exists():return json.loads(receipt.read_text())
 cmd=recipe(arm,obj);cmd=['-g0' if x=='-g' else 'large-unit-insns='+str(value) if x.startswith('large-unit-insns=') else x for x in cmd]
 if not any(x.startswith('large-unit-insns=') for x in cmd): cmd+=['--param','large-unit-insns='+str(value)]
 cmd[cmd.index('-o')+1]=str(dest);cmd+=['-fdump-ipa-inline','-dumpbase',str(OUT/tag)]
 with (OUT/(tag+'.log')).open('w') as log:
  subprocess.run(cmd,cwd=PRE if arm=='pre' else ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
 dump,=OUT.glob(tag+'*.inline')
 with dump.open() as f:unit=next(int(m[1]) for line in f if (m:=re.search(r'Starting with size (\d+)',line)))
 dump.unlink()
 elf=audit.Elf(dest)
 digest=hashlib.sha256(repr([(s,elf.canonical(f)) for s,f in sorted(elf.functions().items())]).encode()).hexdigest()
 result=dict(job,unit=unit,command=cmd,output=str(dest),code_digest=digest)
 receipt.write_text(json.dumps(result,indent=2)+'\n');print('compiled',tag,'IPA',unit,flush=True)
 return result

def score(job):
 receipt=Path(job['output']+'.score.json')
 if receipt.exists():return json.loads(receipt.read_text())
 binary=Path(job['output']+'.tomokv')
 cmd=shlex.split(next(s for s in subprocess.check_output(['make','-n','-W','build/src/main.o','all'],cwd=ROOT,text=True).splitlines() if s.startswith('g++ ') and ' -Wl,--wrap=main ' in s))
 cmd[cmd.index('build/'+job['object'])]=job['output'];cmd[cmd.index('-o')+1]=str(binary);cmd+=['-Wl,--strip-debug']
 with open(job['output']+'.link.log','w') as log:subprocess.run(cmd,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
 post=identity.inventory(binary);refs={arm:identity.inventory(path) for arm,path in identity.REFS.items()}
 rows=identity.compare(post,refs)
 # First preserve command bodies, then single-lane/unchanged hot bodies, then
 # minimize residual hot and all-body changes. Composites remain fully listed.
 result=dict(job,score=[sum(r['command_hot'] and not r['matches'] for r in rows),
   sum(r['hot'] and len(r['changed_lanes'])<=1 and not r['matches'] for r in rows),
   sum(r['hot'] and not r['matches'] for r in rows),sum(not r['matches'] for r in rows)],
   linked_sha256=post['sha256'],link_command=cmd,
   residual_hot=[r for r in rows if r['hot'] and not r['matches']])
 receipt.write_text(json.dumps(result,indent=2)+'\n');binary.unlink();print('scored',job['object'],job['budget'],result['score'],flush=True)
 return result

def main():
 OUT.mkdir(parents=True,exist_ok=True);DOC.mkdir(parents=True,exist_ok=True)
 old,new=budgets(PRE/'Makefile'),budgets(ROOT/'Makefile');phase=sys.argv[1]
 only=set(os.getenv('WAVE9_BUDGET_OBJECTS','').split())
 if only:
  old={k:v for k,v in old.items() if k in only}
  new={k:v for k,v in new.items() if k in only}
 for obj,value in new.items(): old.setdefault(obj,value)
 if phase=='initial':jobs=[dict(arm=a,object=o,budget=n) for a,bs in [('pre',old),('post',new)] for o,n in bs.items()]
 elif phase=='scan':
  rows=json.loads((DOC/'initial.json').read_text());by={(r['arm'],r['object']):r for r in rows};jobs=[]
  for obj,value in new.items():
   center=old[obj]+by['post',obj]['unit']-by['pre',obj]['unit']
   for n in sorted({value,center-8,center,center+8}):jobs.append(dict(arm='post',object=obj,budget=n,derived=center))
 elif phase=='select':
  rows=json.loads((DOC/'scan.json').read_text());unique={}
  for row in rows:unique.setdefault((row['object'],row['code_digest']),row)
  with ProcessPoolExecutor(max_workers=6) as pool:scores=list(pool.map(score,unique.values()))
  by={(r['object'],r['code_digest']):r for r in scores};choices=[]
  for obj,value in new.items():
   opts=[dict(r,score=by[r['object'],r['code_digest']]['score']) for r in rows if r['object']==obj]
   best=min(opts,key=lambda r:(r['score'],r['budget']!=value,abs(r['budget']-r['derived'])))
   choices.append(dict(object=obj,old=value,budget=best['budget'],score=best['score'],trials=opts))
  (DOC/'selected.json').write_text(json.dumps(choices,indent=2)+'\n')
  for r in choices:print(r['object'],r['old'],'->',r['budget'],r['score'],flush=True)
  return
 else:raise ValueError(phase)
 with ProcessPoolExecutor(max_workers=32) as pool:rows=list(pool.map(trial,jobs))
 rows=[dict(r,**j) for r,j in zip(rows,jobs)];(DOC/(phase+'.json')).write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
