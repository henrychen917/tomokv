import pathlib,shutil,subprocess,shlex,json
root=pathlib.Path.cwd();out=root/'build/txnfix3/prepare-args';out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
p=out/'src/cmd/scatter_engine.inc';s=p.read_text().replace('bool txn_group_prepare(ScatterState&, Server&, uint32_t,\n                                        ScatterArenaPool* = nullptr);','bool txn_group_prepare(ScatterState&, ScatterArenaPool* = nullptr);').replace('txn_group_prepare(*state, server, owner_io, &pool)','txn_group_prepare(*state, &pool)');p.write_text(s)
p=out/'src/cmd/txn_group.inc';s=p.read_text().replace('bool txn_group_prepare(ScatterState& state, Server& server, uint32_t io,\n                       ScatterArenaPool* pool) {','bool txn_group_prepare(ScatterState& state, ScatterArenaPool* pool) {\n    auto& server = *state.server;\n    const uint32_t io = state.owner_io;').replace('txn_group_prepare(*next, server, self.id())','txn_group_prepare(*next)');p.write_text(s)
source='src/cmd/xshard.cc';recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
cmd=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l));cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','124-127',*cmd]
with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
(out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(rc)
