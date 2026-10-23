import pathlib,shutil,subprocess,shlex,json
root=pathlib.Path.cwd();out=root/'build/txnfix3/prepare-last';out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
p=out/'src/cmd/scatter_engine.inc';s=p.read_text();a=s.index('    if (state->atomic_group && !force_atomic &&\n');b=s.index('    dispatch.state = state;',a);block=s[a:b];s=s[:a]+s[b:];end=s.index('    return ScatterPrepare::Ready;\n}',a);block=block.replace('        set_oom(op);','        dispatch = {};\n        set_oom(op);');block=block.replace('    }\n','    }\n',1);s=s[:end]+block+s[end:];s=s.replace('    return ScatterPrepare::Ready;\n}', '    dispatch.barrier = state->barrier;\n    return ScatterPrepare::Ready;\n}',1);s=s.replace('    dispatch.barrier = state->barrier;\n', '', 1);p.write_text(s)
source='src/cmd/xshard.cc';recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
cmd=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l));cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','124-127',*cmd]
with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
(out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(rc)
