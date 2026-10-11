import sys,pathlib,subprocess,json,time,hashlib,signal
sys.path.insert(0,'tests/txnfix_audit')
import resp
root=pathlib.Path('docs/txnfix/txnfix3/final-extras').resolve();root.mkdir(exist_ok=True)
data=pathlib.Path('build/txnfix3/extras-data').resolve();data.mkdir(exist_ok=True)
while not pathlib.Path('docs/txnfix/txnfix3/final-proof/COMPLETE.json').exists():time.sleep(.5)
runs=[];sha=hashlib.sha256(pathlib.Path('build/tomokv').read_bytes()).hexdigest()
def check(name,cmd,server=None,timeout=180):
 t=time.monotonic()
 with (root/(name+'.log')).open('w') as log:
  try:r=subprocess.run(['taskset','-c','121-127',*cmd],stdout=log,stderr=subprocess.STDOUT,timeout=timeout);rc=r.returncode
  except subprocess.TimeoutExpired:rc=124
 runs.append(dict(name=name,command=cmd,server=server.argv if server else None,exit_code=rc,seconds=time.monotonic()-t,sha256=sha));print(name,rc,flush=True)
 (root/'runs.json').write_text(json.dumps(runs,indent=2)+'\n');return rc
for mode in ('2s','1s'):
 resp._options.mode=mode;resp._options.databases=16
 for atomic in ('0','1'):
  resp._options.atomic=atomic
  name=f'writer-{mode}-a{atomic}';folder=root/name;folder.mkdir(exist_ok=True);(data/name).mkdir(parents=True,exist_ok=True)
  server=resp.Server(22601,['--enable-debug-command','yes','--read-local','1' if mode=='1s' else '0'],log=str(folder/'server.log'))
  try:check(name,['python3','tests/writer_atomic.py','127.0.0.1','22601','--command','multi-mset','--pattern','full','--writers','2','--keys','8','--seconds','60','--tomokv-mode',atomic,'--json-out',str(folder/'data.json')],server)
  finally:server.stop()
 resp._options.atomic='1'
 name='aof-'+mode;folder=root/name;folder.mkdir(exist_ok=True);(data/name).mkdir(parents=True,exist_ok=True)
 args=['--enable-debug-command','yes','--read-local','1' if mode=='1s' else '0','--appendonly','yes','--appendfsync','no','--dir',str(data/name)]
 server=resp.Server(22601,args,log=str(folder/'prepare-server.log'))
 try:
  rc=check(name+'-prepare',['python3','tests/aof_torn_group.py','127.0.0.1','22601','prepare',str(folder/'state.json')],server)
  if rc==0:server.proc.wait(timeout=30)
 finally:server.stop()
 if rc==0:
  server=resp.Server(22601,args,log=str(folder/'replay-server.log'))
  try:
   check(name+'-verify',['python3','tests/aof_torn_group.py','127.0.0.1','22601','verify',str(folder/'state.json')],server)
   check(name+'-scan',['python3','tests/aof_torn_group.py','127.0.0.1','22601','scan',str(data/name/'appendonlydir/appendonly.aof.1.incr.tomo')],server)
  finally:server.stop()
 for write,atomic,saves in [('mset','1','5'),('exec','0','3')]:
  resp._options.atomic=atomic
  name=f'snapshot-{mode}-{write}';folder=root/name;folder.mkdir(exist_ok=True);(data/name).mkdir(parents=True,exist_ok=True)
  args=['--enable-debug-command','yes','--read-local','1' if mode=='1s' else '0','--dir',str(data/name),'--dbfilename','groups.tomo']
  server=resp.Server(22601,args,log=str(folder/'server.log'))
  try:check(name,['python3','tests/snap_cut_battery.py','22601','atomic_groups',str(data/name/'groups.tomo'),write,saves],server,timeout=180)
  finally:server.stop()

from types import SimpleNamespace
root.mkdir(exist_ok=True)
assert not resp.port_open(22601)
flip_argv=['taskset','-c','112-119',str(pathlib.Path('build/tomokv').resolve()),'--bind','127.0.0.1','--port','22601','--save','','--appendonly','no','--thread-mode','2s','--ratio','6:2','--shards','16','--databases','16','--atomic','1','--key-lb','0','--client-lb','0','--flip-auto','1','--enable-debug-command','yes']
with (root/'flip-server.log').open('w') as out:
 child=subprocess.Popen(flip_argv,stdout=out,stderr=subprocess.STDOUT,cwd=str(data))
 try:
  deadline=time.monotonic()+30
  while True:
   try:
    c=resp.Conn(22601);assert c.cmd('PING')=='PONG';c.close();break
   except OSError:
    assert child.poll() is None
    if time.monotonic()>deadline:raise TimeoutError('FLIP readiness')
    time.sleep(.05)
  check('flip',['python3','tests/flip_multikey_hold.py','127.0.0.1','22601'],SimpleNamespace(argv=flip_argv),timeout=360)
 finally:
  child.terminate()
  try:child.wait(timeout=30)
  except subprocess.TimeoutExpired:child.kill();child.wait(timeout=10)
for mode in ('2s','1s'):
 resp._options.mode=mode;resp._options.databases=16
 for atomic in ('0','1'):
  resp._options.atomic=atomic
  name=f'pre-txniso-{mode}-a{atomic}'
  server=resp.Server(22601,['--enable-debug-command','yes','--read-local','1' if mode=='1s' else '0'],binary=str(pathlib.Path('build/txnfix2/pre/tomokv').resolve()),log=str(root/(name+'-server.log')))
  try:check(name,['python3','tests/txniso.py','127.0.0.1','22601','--mode',mode,'--pre'],server,timeout=180)
  finally:server.stop()
(root/'COMPLETE.json').write_text(json.dumps(dict(rows=len(runs),passed=sum(r['exit_code']==0 for r in runs)),indent=2)+'\n')
