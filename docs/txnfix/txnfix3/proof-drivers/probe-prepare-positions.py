import pathlib,shutil,subprocess,shlex,json,concurrent.futures,re
root=pathlib.Path.cwd();source='src/cmd/xshard.cc';recipe=subprocess.check_output(['make','-n','-W',source,'build/src/cmd/xshard.o'],text=True).replace('\\\n',' ')
base=shlex.split(next(l for l in recipe.splitlines() if ' -c '+source+' ' in l))
def run(variant):
 out=root/'build/txnfix3'/('prepare-'+variant);out.mkdir(exist_ok=True);shutil.copytree(root/'src',out/'src',dirs_exist_ok=True)
 p=out/'src/cmd/scatter_engine.inc';s=p.read_text();start=s.index('ScatterPrepare xshard_prepare(');end=s.index('\nint32_t xshard_dispatch_shard(',start)
 at=s.index({'captureclock':'    state->now_cut_ms =', 'capturesnapshot':'    if (needs_snapshot) {', 'captureset':'    if (kind == Kind::Sintercard) {', 'captureadmitted':'    state->admitted = admitted;'}[variant],start)
 segment=re.sub(r'(?<!->)\bkind\b','prepared_kind',s[at:end]);s=s[:at]+'    const Kind prepared_kind = kind;\n'+segment+s[end:];p.write_text(s)
 cmd=base.copy();cmd[cmd.index(source)]=str(out/source);cmd[cmd.index('-o')+1]=str(out/'xshard.o');cmd+=['-g0'];cmd=['taskset','-c','112-127',*cmd]
 with (out/'build.log').open('w') as log:rc=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 (out/'build.json').write_text(json.dumps(dict(command=cmd,exit_code=rc),indent=2)+'\n');print(variant,rc,flush=True)
 if rc:return
 dest=root/'build/txnfix3/scatter-probe'/('prepare-'+variant);dest.mkdir(exist_ok=True)
 link=json.loads((root/'docs/txnfix/txnfix3/scatter-trace/build.json').read_text())[1]['link'];link=[str(out/'xshard.o') if x=='build/src/cmd/xshard.o' else x for x in link];link[link.index('-o')+1]=str(dest/'probe')
 with (out/'link.log').open('w') as log:subprocess.run(link,stdout=log,stderr=subprocess.STDOUT,check=True)
with concurrent.futures.ThreadPoolExecutor(4) as pool:list(pool.map(run,['captureclock','capturesnapshot','captureset','captureadmitted']))
