import pathlib,shutil,subprocess,shlex,json,concurrent.futures
root=pathlib.Path.cwd()
source='src/cmd/xshard.cc';recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
base=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l))
def run(variant):
 out=root/'build/txnfix3'/('prepare-'+variant);out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
 p=out/'src/cmd/scatter_engine.inc';s=p.read_text()
 decl='[[gnu::noinline]] bool txn_group_dispatch_prepare(ScatterState&, ScatterArenaPool&);\n'
 s=s.replace('enum class TxnGroupRead',decl+'enum class TxnGroupRead')
 old='''        ((!txn_group_prepare(*state, server, owner_io, &pool)) ||
         ((state->atomic_write || state->atomic_direct) &&
          !aof_prepare_scatter_group(*state))))'''
 condition='''        !txn_group_dispatch_prepare(*state, pool))'''
 if variant=='wrappedflags':condition='''        (state->atomic_write || state->atomic_apply) &&
        !txn_group_dispatch_prepare(*state, pool))'''
 assert old in s;s=s.replace(old,condition)
 p.write_text(s)
 p=out/'src/cmd/txn_group.inc';s=p.read_text();pos=s.index('// Called only after an existing lifetime predicate')
 s=s[:pos]+'''bool txn_group_dispatch_prepare(ScatterState& state, ScatterArenaPool& pool) {
    return txn_group_prepare(state, *state.server, state.owner_io, &pool) &&
        (!(state.atomic_write || state.atomic_direct) || aof_prepare_scatter_group(state));
}

'''+s[pos:];p.write_text(s)
 cmd=base.copy();cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 (out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(variant,rc,flush=True)
 if rc:return
 arm='prepare-'+variant;dest=root/'build/txnfix3/scatter-probe'/arm;dest.mkdir(exist_ok=True)
 link=json.loads((root/'docs/txnfix/txnfix3/scatter-trace/build.json').read_text())[1]['link']
 link=[str(out/'xshard.o') if x=='build/src/cmd/xshard.o' else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
 with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(2) as pool:list(pool.map(run,['wrapped','wrappedflags']))
