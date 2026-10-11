import pathlib,shutil,subprocess,shlex,json,concurrent.futures
root=pathlib.Path.cwd();source='src/cmd/xshard.cc'
recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
base=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l))
def run(variant):
 out=root/'build/txnfix3'/('prepare-'+variant);out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
 p=out/'src/cmd/scatter_engine.inc';s=p.read_text();start=s.index('ScatterPrepare xshard_prepare(')
 if variant=='constkind':
  stop=s.index('    if (kind == Kind::Swapdb && origin_client)',start)
  a=s[start:stop].replace('Kind kind;', 'Kind classified_kind;').replace('kind =','classified_kind =').replace('classify(op, kind)', 'classify(op, classified_kind)')
  s=s[:start]+a+'    const Kind kind = classified_kind;\n\n'+s[stop:]
 elif variant=='statekind':
  pos=s.index('    if (kind == Kind::Swapdb && !server.databases().admit_swap(state))',start)
  s=s[:pos]+s[pos:].replace('if (kind == Kind::Swapdb', 'if (state->kind == Kind::Swapdb',1)
 else:
  s=s.replace('''        ((!txn_group_prepare(*state, server, owner_io, &pool)) ||
         ((state->atomic_write || state->atomic_direct) &&
          !aof_prepare_scatter_group(*state))))''','''        (state->atomic_write || state->atomic_direct) &&
        !aof_prepare_scatter_group(*state))''')
 p.write_text(s)
 cmd=base.copy();cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 (out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(variant,rc,flush=True)
 if rc:return
 arm='prepare-'+variant;dest=root/'build/txnfix3/scatter-probe'/arm;dest.mkdir(exist_ok=True)
 link=json.loads((root/'docs/txnfix/txnfix3/scatter-trace/build.json').read_text())[1]['link'];link=[str(out/'xshard.o') if x=='build/src/cmd/xshard.o' else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
 with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(3) as pool:list(pool.map(run,['constkind','statekind','original']))
