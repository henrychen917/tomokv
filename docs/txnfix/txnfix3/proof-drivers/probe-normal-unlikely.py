import pathlib,shutil,subprocess,shlex,json,concurrent.futures
root=pathlib.Path.cwd();source='src/cmd/xshard.cc'
recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
base=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l))
def run(variant):
 out=root/'build/txnfix3'/('normal-'+variant);out.mkdir(exist_ok=True)
 start=root/'build/txnfix3/db0-kind-plan/src' if variant.startswith('plan-') else root/'src'
 shutil.copytree(start,out/'src',dirs_exist_ok=True)
 p=out/'src/cmd/scatter_engine.inc';s=p.read_text()
 if variant=='unlikely':s=s.replace('if (state->atomic_group && !force_atomic &&','if (__builtin_expect(state->atomic_group && !force_atomic, false) &&',1)
 elif variant=='cold':s=s.replace('[[gnu::noinline]] bool txn_group_prepare(', '[[gnu::noinline, gnu::cold]] bool txn_group_prepare(',1)
 else:
  flag='align-loops=8' if variant=='plan-align8' else 'align-loops=16:12:8'
  s=s.replace('ScatterPrepare xshard_prepare(', '[[gnu::optimize("'+flag+'")]]\nScatterPrepare xshard_prepare(',1)
 p.write_text(s)
 cmd=base.copy();cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 (out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(variant,rc,flush=True)
 if rc:return
 dest=root/'build/txnfix3'/('prepare-'+variant)/'post-normal';dest.mkdir(parents=True,exist_ok=True)
 link=next(r['link'] for r in json.loads((root/'docs/txnfix/txnfix3/prepare-release/build.json').read_text()) if r['arm']=='post-normal')
 link=[str(out/'xshard.o') if x=='build/src/cmd/xshard.o' else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
 with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(run,['unlikely']))
