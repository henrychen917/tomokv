"""Compile-only per-unit IPA derivation; all trials stay inside the lane."""
from concurrent.futures import ThreadPoolExecutor
import json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=ROOT/'build/bugs5/budgets';OUT.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'tools'))
from ccfix4_budget import inventory,compare
commands={}
for line in (ROOT/'docs/bugs5/build-pre.log').read_text().splitlines():
 if line.startswith('g++ ') and ' -c ' in line:
  c=shlex.split(line);commands[c[-1]]=c
units=['build/'+prefix+unit for prefix in ('src/','db0/src/')
       for unit in ('main.o','core/genthread.o','core/rl2s.o','cmd/t_hash.o')]
def trial(obj,arm,budget=None):
 tag=obj.replace('/','_')+'-'+arm+('-'+str(budget) if budget is not None else '')
 dest=OUT/tag
 command=commands[obj].copy();command[command.index('-o')+1]=str(dest)+'.o'
 if budget is not None:
  command=[f'large-unit-insns={budget}' if a.startswith('large-unit-insns=') else a for a in command]
  if 'cmd/t_hash.o' in obj:command+=['--param','inline-unit-growth=0','--param',f'large-unit-insns={budget}']
 command+=['-fdump-ipa-inline','-dumpbase',str(dest)]
 cwd=ROOT/'build/bugs5/pre-source' if arm=='pre' else ROOT
 with open(str(dest)+'.log','w') as log:subprocess.run(command,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
 dump,=OUT.glob(tag+'*.inline')
 with dump.open() as f:initial=next(int(m[1]) for l in f if (m:=re.search(r'Starting with size (\d+)',l)))
 dump.unlink()
 result=dict(object=obj,arm=arm,budget=budget,initial=initial,command=command)
 if arm!='pre':
  result.update(compare(inventory(ROOT/'build/bugs5/pre-source'/obj),inventory(Path(str(dest)+'.o'))))
 (OUT/(tag+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 print(tag,initial,result.get('changed'),flush=True)
 return result
if __name__=='__main__':
 with ThreadPoolExecutor(max_workers=8) as p:initial=list(p.map(lambda x:trial(*x),[(o,a) for o in units for a in ('pre','post')]))
 jobs=[]
 for obj in units:
  old,new=[next(r for r in initial if r['object']==obj and r['arm']==a) for a in ('pre','post')]
  budget=next((int(a.split('=')[1]) for a in commands[obj] if a.startswith('large-unit-insns=')),None)
  derived=budget+new['initial']-old['initial'] if budget else old['initial']*140//100
  for candidate in (derived-8,derived,derived+8):jobs.append((obj,'derived',candidate))
 with ThreadPoolExecutor(max_workers=8) as p:trials=list(p.map(lambda x:trial(*x),jobs))
 (ROOT/'docs/bugs5/budget-trials.json').write_text(json.dumps(initial+trials,indent=2)+'\n')
