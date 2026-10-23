"""Compile-only IPA derivation; inherited CPU mask is 48-63, no live workloads."""
from concurrent.futures import ThreadPoolExecutor
import json,re,shlex,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/fliplisten/budgets';OUT.mkdir(exist_ok=True)
DOC=ROOT/'docs/fliplisten/budgets';DOC.mkdir(exist_ok=True)
sys.path.insert(0,str(ROOT/'tools'))
from ccfix4_budget import inventory,compare
commands={}
for line in (ROOT/'docs/fliplisten/build-pre.log').read_text().splitlines():
 if line.startswith('g++ ') and ' -c ' in line:
  c=shlex.split(line);commands[c[-1].removeprefix('build/fliplisten-pre/')]=c
units=[prefix+unit for prefix in ('src/','db0/src/') for unit in ('main.o','core/genthread.o','core/rl2s.o','core/reorder.o')]
def trial(obj,arm,budget=None):
 tag=obj.replace('/','_')+'-'+arm+('-'+str(budget) if budget is not None else '')
 dest=OUT/tag
 command=commands[obj].copy();command[command.index('-o')+1]=str(dest)+'.o'
 if budget is not None:command=[f'large-unit-insns={budget}' if a.startswith('large-unit-insns=') else a for a in command]
 command+=['-fdump-ipa-inline','-dumpbase',str(dest)]
 cwd=ROOT/'build/fliplisten/pre-source' if arm=='pre' else ROOT
 with open(str(dest)+'.log','w') as log:subprocess.run(command,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,check=True)
 dump,=OUT.glob(tag+'*.inline')
 with dump.open() as f:initial=next(int(m[1]) for l in f if (m:=re.search(r'Starting with size (\d+)',l)))
 dump.unlink()
 result=dict(object=obj,arm=arm,budget=budget,initial=initial,command=command)
 if arm!='pre':
  result.update(compare(inventory(ROOT/'build/fliplisten-pre'/obj),inventory(Path(str(dest)+'.o'))))
  result['score']=[sum(r['hot'] and r['differing_bytes'] and not any(s in r['name'] for s in ('on_cqe<','on_accept<','epoll_pass<','admit_fd<')) for r in result['rows']), result['hot_differing_bytes'], result['changed']]
 (DOC/(tag+'.json')).write_text(json.dumps(result,indent=2)+'\n')
 print(tag,initial,result.get('score'),flush=True)
 return result
if __name__=='__main__':
 frozen=json.loads((DOC/'initial.json').read_text())
 with ThreadPoolExecutor(max_workers=8) as pool:initial=[r for r in frozen if r['arm']=='pre']+list(pool.map(lambda o:trial(o,'post'),units))
 (DOC/'initial.json').write_text(json.dumps(initial,indent=2)+'\n')
 jobs=[]
 for obj in units:
  old,new=[next(r for r in initial if r['object']==obj and r['arm']==a) for a in ('pre','post')]
  budget=next(int(a.split('=')[1]) for a in commands[obj] if a.startswith('large-unit-insns='))
  derived=budget+new['initial']-old['initial']
  for candidate in sorted({derived-8,derived,derived+8}):jobs.append((obj,'derived',candidate))
 with ThreadPoolExecutor(max_workers=8) as pool:trials=list(pool.map(lambda x:trial(*x),jobs))
 (DOC/'trials.json').write_text(json.dumps(trials,indent=2)+'\n')
 choices=[]
 for obj in units:
  opts=[r for r in initial+trials if r['object']==obj and r['arm']!='pre']
  best=min(opts,key=lambda r:(r['score'],r['budget'] is not None))
  choices.append({k:v for k,v in best.items() if k!='rows'})
 (DOC/'selected.json').write_text(json.dumps(choices,indent=2)+'\n')
