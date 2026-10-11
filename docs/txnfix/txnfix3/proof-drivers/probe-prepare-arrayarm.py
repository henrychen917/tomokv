import pathlib,shutil,subprocess,shlex,json
root=pathlib.Path.cwd();out=root/'build/txnfix3/prepare-arrayarm';out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
p=out/'src/cmd/scatter_engine.inc';s=p.read_text();s=s.replace('''        ((!txn_group_prepare(*state, server, owner_io, &pool)) ||
         ((state->atomic_write || state->atomic_direct) &&
          !aof_prepare_scatter_group(*state))))''','''        (state->atomic_write || state->atomic_direct) &&
        !aof_prepare_scatter_group(*state))''')
old="""    if (state.shard_groups)
        std::fill_n(state.shard_groups, state.shard_slots, UINT16_MAX);
"""
assert old in s;s=s.replace(old,'',1)
pos=s.index('\n}\n\nvoid reset_groups(ScatterState& state)')
s=s[:pos]+"""\n    if (state.shard_groups) {
        std::fill_n(state.shard_groups, state.shard_slots, UINT16_MAX);
        if (state.admitted && !txn_group_prepare(state, *state.server, state.owner_io))
            throw std::bad_alloc{};
    }
"""+s[pos:]
s=s.replace('    init_arena_arrays(*state);','''    try {
        init_arena_arrays(*state);
    } catch (const std::bad_alloc&) {
        if (routes != route_stack) delete[] routes;
        xshard_abandon_unpublished(state, pool, owner_io);
        set_oom(op);
        return ScatterPrepare::Error;
    }''',1)
p.write_text(s)
source='src/cmd/xshard.cc';recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
cmd=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l));cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
(out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(rc,flush=True)
if rc:raise SystemExit(rc)
dest=root/'build/txnfix3/scatter-probe/prepare-arrayarm';dest.mkdir(exist_ok=True)
link=json.loads((root/'docs/txnfix/txnfix3/scatter-trace/build.json').read_text())[1]['link'];link=[str(out/'xshard.o') if x=='build/src/cmd/xshard.o' else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
