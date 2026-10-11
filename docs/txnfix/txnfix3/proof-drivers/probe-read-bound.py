import pathlib,shutil,subprocess,shlex,json,concurrent.futures
root=pathlib.Path.cwd();source='src/cmd/xshard.cc'
def run(case):
 ns,variant=case;rel=('db0/' if ns=='db0' else '')+source[:-3]+'.o'
 recipe=subprocess.check_output(['make','-n','-W',source,'build/'+rel],text=True).replace('\\\n',' ')
 base=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l))
 out=root/'build/txnfix3'/('bound-'+ns+'-'+variant);out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
 p=out/'src/cmd/scatter_engine.inc';s=p.read_text();s=s.replace('if (bound) store.atomic_set_read_context(', 'if (__builtin_expect(bound, true)) store.atomic_set_read_context(',1)
 if variant=='both':s=s.replace('if (bound) store.atomic_clear_read_epoch();','if (__builtin_expect(bound, true)) store.atomic_clear_read_epoch();',1)
 p.write_text(s);cmd=base.copy();cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 (out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(ns,variant,rc,flush=True)
 if rc:return
 folder=root/'build/txnfix3'/('read-bound-'+variant)/('post-'+ns);folder.mkdir(parents=True,exist_ok=True)
 link=next(r['link'] for r in json.loads((root/'docs/txnfix/txnfix3/read-certified/build.json').read_text()) if r['arm']=='post-'+ns)
 link=[str(out/'xshard.o') if x=='build/'+rel else x for x in link];link[link.index('-o')+1]=str(folder/'probe')
 with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(run,[(ns,v) for ns in ['normal','db0'] for v in ['ctor','both']]))
