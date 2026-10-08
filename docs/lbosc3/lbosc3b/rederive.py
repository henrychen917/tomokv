from concurrent.futures import ThreadPoolExecutor
import json,subprocess,sys
from pathlib import Path
sys.path.insert(0,'tools')
from lbstall_artifacts import Elf,HOT
root=Path('build/lbosc3/lbosc3b/budgets'); root.mkdir(exist_ok=True)
old={}
for db0 in (False,True):
 p=Path('build/lbosc3/PRE') / ('db0/src/main.o' if db0 else 'src/main.o')
 e=Elf(p); fs=e.functions(); names=list(fs)
 dem=subprocess.check_output(['c++filt'],input='\n'.join(names)+'\n',text=True).splitlines()
 old[db0]={n:(d,e.canonical(fs[n])) for n,d in zip(names,dem) if HOT.search(d)}
def trial(pair):
 db0,n,auto=pair; label=('db0-main-' if db0 else 'main-')+str(n)+'-a'+str(auto); out=root/(label+'.o')
 cmd=['taskset','-c','112-127','g++','-std=c++20','-O2','-g0','-Wall','-Wextra','-march=native','-pthread','-DTOMO_JEMALLOC','--param','inline-unit-growth=0','--param','large-unit-insns='+str(n),'-I.']
 cmd+=['-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0'] if db0 else ['-DTOMO_DUAL_DATABASE']
 cmd+=['--param','max-inline-insns-auto='+str(auto)]
 cmd+=['-c','src/main.cc','-o',str(out)]
 with (root/(label+'.log')).open('w') as log: subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
 e=Elf(out); fs=e.functions()
 rows=[dict(symbol=k,name=v[0],equal=k in fs and e.canonical(fs[k])==v[1]) for k,v in old[db0].items()]
 report=dict(command=cmd,total=len(rows),matched=sum(r['equal'] for r in rows),changed=[r['name'] for r in rows if not r['equal']])
 (root/(label+'.json')).write_text(json.dumps(report,indent=2)+'\n')
 print(label,report['matched'],report['total'],report['changed'],flush=True)
values=[(True,n,14) for n in (146320,146330,146348,146360,146380,146400)]
with ThreadPoolExecutor(max_workers=3) as pool: list(pool.map(trial,values))
