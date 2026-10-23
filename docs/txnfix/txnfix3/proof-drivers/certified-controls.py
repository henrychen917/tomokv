import pathlib,json,subprocess,time,hashlib,sys
sys.path.insert(0,'tests/txnfix_audit');import resp
root=pathlib.Path('docs/txnfix/txnfix3/certified-controls');root.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/certified-cross-watch/COMPLETE.json').exists():time.sleep(.5)
rows=[]
cases=[('pre','build/txnfix2/pre/tomokv','1s',test) for test in ('execatomic','atomic_torn')]
for mode in ('2s','1s'):cases.append(('post','build/tomokv',mode,'G5'))
for arm,binary,mode,test in cases:
 name=f'{arm}-{mode}-{test}';folder=root/name;folder.mkdir(exist_ok=True)
 resp._options.mode=mode;resp._options.atomic='1';resp._options.databases=16
 server=resp.Server(22601,['--enable-debug-command','yes','--read-local','1' if mode=='1s' else '0'],binary=str(pathlib.Path(binary).resolve()),log=str(folder/'server.log'))
 try:
  args=['tests/txngroup.py','127.0.0.1','22601','--mode',mode,'--only','G5'] if test=='G5' else ['tests/'+test+'.py','127.0.0.1','22601']
  cmd=['taskset','-c','121-127','python3',*args];started=time.monotonic()
  with (folder/'test.log').open('w') as out:
   try:rc=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT,timeout=240).returncode
   except subprocess.TimeoutExpired:rc=124
  rows.append(dict(name=name,arm=arm,command=cmd,server=server.argv,exit_code=rc,seconds=time.monotonic()-started,sha256=hashlib.sha256(pathlib.Path(binary).read_bytes()).hexdigest()))
  (root/'runs.json').write_text(json.dumps(rows,indent=2)+'\n');print(name,rc,flush=True)
 finally:
  code=server.stop();(folder/'shutdown.json').write_text(json.dumps(dict(exit_code=code))+'\n')
(root/'COMPLETE.json').write_text(json.dumps(rows,indent=2)+'\n')

# Rebuild the deliberately broken barrier against this final source and objects.
cmd=['taskset','-c','112-127','python3','tools/txnfix_barrier_control.py','--output','build/txnfix3/certified-barrier-off','--receipt','docs/txnfix/txnfix3/certified-barrier-control']
with pathlib.Path('build/txnfix3/certified-barrier-build.log').open('w') as out:subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT,check=True)
subprocess.run(['taskset','-c','112-127','python3','build/txnfix3/certified-barrier-control.py'],check=True)
for control in ['unfenced','undrained']:
 cmd=['taskset','-c','112-127','python3','tools/txnfix_admission_control.py',control]
 with (root/('admission-'+control+'.log')).open('w') as out:rc=subprocess.run(cmd,stdout=out,stderr=subprocess.STDOUT).returncode
 assert rc != 0, control+' negative control unexpectedly passed'

(root/'ALL-DONE').touch()
