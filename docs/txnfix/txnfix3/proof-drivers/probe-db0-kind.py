import pathlib,shutil,subprocess,shlex,json,concurrent.futures
root=pathlib.Path.cwd();source='src/cmd/xshard.cc'
recipe=subprocess.check_output(['make','-n','-W',source,'build/db0/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
base=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l))
def run(variant):
 out=root/'build/txnfix3'/('db0-kind-'+variant);out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
 p=out/'src/cmd/scatter_engine.inc';s=p.read_text();start=s.index('    // Parsing takes kind by address.');end=s.index('\nint32_t xshard_dispatch_shard(',start)
 body=s[start:end];stop=body.index('    if (needs_snapshot) {');body=body[stop:].replace('prepared_kind','kind')
 s=s[:start]+body+s[end:]
 if variant=='clock':
  import re
  start=s.index('    state->now_cut_ms =',s.index('ScatterPrepare xshard_prepare('));end=s.index('\nint32_t xshard_dispatch_shard(',start)
  s=s[:start]+'    const Kind prepared_kind = kind;\n'+re.sub(r'(?<!->)\bkind\b','prepared_kind',s[start:end])+s[end:]
 p.write_text(s)
 cmd=base.copy();cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 (out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(variant,rc,flush=True)
 if rc:return
 dest=root/'build/txnfix3'/('prepare-'+variant)/'post-db0';dest.mkdir(parents=True,exist_ok=True)
 link=next(r['link'] for r in json.loads((root/'docs/txnfix/txnfix3/prepare-release/build.json').read_text()) if r['arm']=='post-db0')
 link=[str(out/'xshard.o') if x=='build/db0/src/cmd/xshard.o' else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
 with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(run,['original','clock']))
