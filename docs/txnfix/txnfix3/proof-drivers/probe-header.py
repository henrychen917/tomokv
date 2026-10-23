import concurrent.futures, json, pathlib, shlex, shutil, subprocess, sys
sys.path.insert(0,'tools');from ccfix_audit import audit
root=pathlib.Path('.').resolve(); out=root/'build/txnfix3/header-probe';out.mkdir(exist_ok=True)
for arm in ('owner','both'):
 base=out/arm
 shutil.copytree(root/'src',base/'src',dirs_exist_ok=True)
 p=base/'src/cmd/multi.h';s=p.read_text().replace('    uint32_t owner_io = 0;            // fits the existing tail padding\n','')
 if arm=='both':s=s.replace('GroupExclusive, GroupBarriers, Count','GroupExclusive, Count')
 p.write_text(s)
def run(item):
 arm,obj=item;source=obj.removeprefix('db0/').removesuffix('.o')+'.cc'
 text=subprocess.check_output(['make','-n','-W',source,'build/'+obj],text=True)
 cmd=shlex.split(next(l for l in text.splitlines() if ' -c '+source+' ' in l))
 target=out/arm/obj.replace('/','_');cmd[cmd.index(source)]=str(out/arm/source);cmd[cmd.index('-o')+1]=str(target);cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with target.with_suffix('.log').open('w') as f:subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,check=True)
 a,b=audit.Elf(root/'build/txnfix2/pre'/obj),audit.Elf(target);old,new=a.functions(),b.functions();syms=list(old);names=subprocess.check_output(['c++filt'],input='\n'.join(syms),text=True).splitlines()
 rows=[dict(name=n,equal=s in new and a.canonical(old[s])==b.canonical(new[s])) for s,n in zip(syms,names) if audit.HOT.search(n)]
 result=dict(arm=arm,object=obj,changed=sum(not r['equal'] for r in rows),rows=rows,command=cmd);target.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n');print(arm,obj,result['changed'],flush=True)
with concurrent.futures.ThreadPoolExecutor(4) as p:list(p.map(run,[(a,o) for a in ('owner','both') for o in ('src/core/rl2s.o','db0/src/core/reorder.o')]))
