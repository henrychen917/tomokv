import hashlib,json,os,signal,socket,subprocess,sys,time
from pathlib import Path
root=Path.cwd();base=root/'build/flipfix6/txnorder-recheck';base.mkdir(exist_ok=True)
receipt=root/'docs/flipfix6/txnorder-recheck.json';rows=[]
if receipt.exists():
 previous=json.loads(receipt.read_text())
 native_done=root/'docs/flipfix6/txnorder-native-recheck.json'
 if len(previous)==16 and all('normal_exit' in x for x in previous) and native_done.exists() and len(json.loads(native_done.read_text()))==4:
  print('Matched diagnosis already complete; retaining original results',flush=True);sys.exit(0)
env={**os.environ,'LC_ALL':'C'}
for n in range(8):
 for arm in ('PRE','POST'):
  name=f'{n+1:02d}-{arm}';d=base/name;d.mkdir();(d/'data').mkdir()
  binary=(root/'build/flipfix6'/arm).resolve()
  server=[str(binary),'--port','20300','--bind','127.0.0.1','--shards','16','--dir',str(d/'data'),'--save','','--net-io','epoll','--thread-mode','fused','--read-local','1','--atomic','1','--databases','16','--enable-debug-command','yes','--key-lb','0','--client-lb','0','--flip-auto','0','--appendonly','yes','--appendfsync','no']
  debugger=['taskset','-c','32-39','gdb','-q','--nx','--batch','-ex','set debuginfod enabled off','-ex','set pagination off','-ex','set confirm off','-ex','set print thread-events off','-ex','set disable-randomization off','-ex','handle SIGPIPE nostop noprint pass','-ex','handle SIGTERM nostop noprint pass','-ex','run','-ex','thread apply all bt 18','--args',*server]
  test=['taskset','-c','40-47','python3','tests/txnorder.py','127.0.0.1','20300','--mode','1s','--only','d']
  row={'case':name,'arm':arm,'binary_sha256':hashlib.sha256(binary.read_bytes()).hexdigest(),'server_argv':server,'debugger_argv':debugger,'test_argv':test,'start':time.time(),'environment':{'LC_ALL':'C'},'manual_abort':False}
  rows.append(row);receipt.write_text(json.dumps(rows,indent=2)+'\n')
  print('START txnorder recheck',name,flush=True)
  with (d/'server-gdb.log').open('w') as log:
   proc=subprocess.Popen(debugger,stdout=log,stderr=subprocess.STDOUT,env=env)
   pid=None;ready=False
   for _ in range(600):
    if proc.poll() is not None:break
    try:
     for child in Path(f'/proc/{proc.pid}/task/{proc.pid}/children').read_text().split():
      try:
       if Path(f'/proc/{child}/exe').resolve()==binary:pid=int(child)
      except OSError:pass
     if pid:
      with socket.create_connection(('127.0.0.1',20300),timeout=.05):ready=True
    except (OSError,ValueError):pass
    if ready:break
    time.sleep(.05)
   row['server_pid']=pid;row['ready']=ready
   if ready:
    with (d/'battery.log').open('w') as output:
     try:r=subprocess.run(test,stdout=output,stderr=subprocess.STDOUT,env=env,timeout=180);row['test_exit']=r.returncode
     except subprocess.TimeoutExpired:row['test_exit']=124
   else:row['test_exit']=125
   if pid:
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:pass
   try:row['debugger_exit']=proc.wait(timeout=12)
   except subprocess.TimeoutExpired:
    row['manual_abort']=True
    if pid:
     try:os.kill(pid,signal.SIGABRT)
     except ProcessLookupError:pass
    try:row['debugger_exit']=proc.wait(timeout=12)
    except subprocess.TimeoutExpired:
     proc.kill();proc.wait();row['debugger_exit']=137
     if pid:
      try:os.kill(pid,signal.SIGKILL)
      except ProcessLookupError:pass
  output=(d/'server-gdb.log').read_text(errors='replace');battery=(d/'battery.log').read_text(errors='replace') if (d/'battery.log').exists() else ''
  row.update(seconds=time.time()-row['start'],same_d_timeout="FAIL d TimeoutError('timed out')" in battery,shutdown_timeout='database worker shutdown timeout' in output,normal_exit='exited normally' in output)
  row['passed']=row['test_exit']==0 and row['normal_exit']
  receipt.write_text(json.dumps(rows,indent=2)+'\n')
  print('END txnorder recheck',name,'test',row['test_exit'],'same_timeout',row['same_d_timeout'],'shutdown_timeout',row['shutdown_timeout'],flush=True)
print('Completed matched PRE/POST diagnosis',flush=True)

native=[];native_receipt=root/'docs/flipfix6/txnorder-native-recheck.json'
for n in range(2):
 for arm in ('PRE','POST'):
  name=f'gate-txnorder-native-{n+1}-{arm}'
  cmd=['taskset','-c','32-47','tests/gate.sh','quick','--server-cores','32-39','--load-cores','40-47','--load-smt','','--ports','20300-20399','--candidate-binary',str(root/'build/flipfix6'/arm)]
  runenv={**env,'GATE_PROOF_NO_RATES':'1','GATE_ONLY_JOBS':'txnorder-fused-1','GATE_NET_IO':'epoll'}
  entry={'name':name,'arm':arm,'argv':cmd,'environment':{k:runenv[k] for k in ('LC_ALL','GATE_PROOF_NO_RATES','GATE_ONLY_JOBS','GATE_NET_IO')},'start':time.time()}
  native.append(entry);native_receipt.write_text(json.dumps(native,indent=2)+'\n')
  print('START',name,flush=True)
  with (root/'build/flipfix6'/(name+'.log')).open('w') as log:r=subprocess.run(cmd,env=runenv,stdout=log,stderr=subprocess.STDOUT)
  entry.update(exit=r.returncode,seconds=time.time()-entry['start'])
  native_receipt.write_text(json.dumps(native,indent=2)+'\n');print('END',name,r.returncode,flush=True)
