import concurrent.futures,hashlib,json,subprocess,sys
from pathlib import Path
root=Path.cwd();sys.path.insert(0,str(root/'tools'))
from lbstall_artifacts import Elf,HOT
baseline=root/'build/storesize2/mainline/build/db0/src'
cases=[('outline_ctor','main',146214),('outline_ctor','rl2s',161715),('outline_ctor','reorder',147380),('outline_ctor','t_server',0),('inline_ctor','main',146214),('inline_ctor','rl2s',161715),('inline_ctor','reorder',147380),('inline_ctor','t_server',0)]
if len(sys.argv)>1: cases=json.loads(sys.argv[1])
def trial(case):
 variant,name,budget=case[:3];extra=case[3] if len(case)>3 else [];src='src/'+('main.cc' if name=='main' else ('cmd/' if name=='t_server' else 'core/')+name+'.cc');directory=root/'build/storesize3'/variant
 out=directory/(f'{name}-{budget}'+('-'+hashlib.sha256(str(extra).encode()).hexdigest()[:8] if extra else '')+'.o');log=out.with_suffix('.log')
 args=['g++','-std=c++20','-O2','-g0','-Wall','-Wextra','-march=native','-pthread','-DTOMO_JEMALLOC','-DTOMO_SINGLE_DATABASE=1','-Dtomo=tomo_db0','-I.']
 if budget:args+=['--param','inline-unit-growth=0','--param',f'large-unit-insns={budget}']
 args+=extra+['-c',src,'-o',str(out)]
 with log.open('w') as stream:subprocess.run(args,cwd=directory,stdout=stream,stderr=subprocess.STDOUT,check=True)
 a,b=Elf(baseline/src.removeprefix('src/').replace('.cc','.o')),Elf(out);old,new=a.functions(),b.functions();names=list(old)
 readable=subprocess.check_output(['c++filt'],input=('\n'.join(names)+'\n').encode()).decode().splitlines();rows=[]
 for n,title in zip(names,readable):
  if not (HOT.search(title) or (name=='t_server' and 'cmd_' in title)):continue
  symbol=new.get(n);rows.append(dict(symbol=n,name=title,pre_size=old[n]['size'],post_size=symbol['size'] if symbol else 0,raw_equal=bool(symbol) and a.body(old[n])==b.body(symbol),relocation_equal=bool(symbol) and a.canonical(old[n])==b.canonical(symbol)))
 out.with_suffix('.json').write_text(json.dumps(rows,indent=2)+'\n')
 bad=[r for r in rows if not r['relocation_equal']];print(variant,name,budget,extra,len(rows),'diff',len(bad),[(r['pre_size'],r['post_size'],r['name'][:120]) for r in bad],flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(trial,cases))
