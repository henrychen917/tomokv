#!/usr/bin/env python3
"""Own the eight fresh stress boots; all assertions live in tests/execfair.py."""
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'))
import _lib
OUT=ROOT/'docs/execfair/stress';OUT.mkdir(exist_ok=True)
# Keep the progress-window proof separate from any debugger trace still running.
while (ROOT/'build/execfair-dispatch-pending').exists() and not (ROOT/'build/execfair-dispatch.exit').exists():
 time.sleep(1)
PORT=30850
binary=ROOT/'build/tomokv'
rows=[]
for mode in ('1s','2s'):
 for atomic in (0,1):
  for shape in ('hot','private'):
   label=f'{mode}-a{atomic}-{shape}'
   directory=ROOT/'build/execfair-stress'/label;directory.mkdir(parents=True,exist_ok=True)
   with socket.socket() as guard:
    guard.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    guard.bind(('127.0.0.1',PORT))
   argv=['taskset','-c','64-71',str(binary),'--bind','127.0.0.1','--port',str(PORT),
         '--thread-mode',mode,'--atomic',str(atomic),'--databases','1',
         '--key-lb','0','--client-lb','0','--flip-auto','0','--enable-debug-command','yes',
         '--dir',str(directory),'--save','']
   argv += ['--read-local','1','--shards','64'] if mode=='1s' else ['--ratio','6:2','--shards','16']
   row=dict(cell=label,server=argv,binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
   with (OUT/(label+'-server.log')).open('w') as log:
    server=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
    try:
     deadline=time.monotonic()+15
     while True:
      assert server.poll() is None,'owned server exited at boot'
      try:
       conn=_lib.Conn('127.0.0.1',PORT,timeout=1)
       info=_lib.info(conn,'server');conn.close()
       assert int(info['process_id'])==server.pid,('listener PID',info,server.pid)
       break
      except (OSError,EOFError):
       assert time.monotonic()<deadline,'boot deadline'
       time.sleep(.05)
     command=['taskset','-c','72-79','python3','tests/execfair.py','127.0.0.1',str(PORT),
              '--shape',shape,'--seconds','60','--clients','64','--output',str(OUT/(label+'.json'))]
     row['client']=command
     with (OUT/(label+'-client.log')).open('w') as clientlog:
      row['exit_code']=subprocess.run(command,cwd=ROOT,stdout=clientlog,
                                     stderr=subprocess.STDOUT,timeout=90).returncode
    except Exception as error:
     row['error']=repr(error);row['exit_code']=1
    finally:
     if server.poll() is None:server.terminate()
     try:row['server_exit']=server.wait(timeout=15)
     except subprocess.TimeoutExpired:
      server.kill();row['server_exit']=server.wait();row['shutdown_timeout']=True
   rows.append(row)
   (OUT/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
   print(label,row,flush=True)
assert len(rows)==8 and all(r['exit_code']==0 and not r.get('shutdown_timeout') for r in rows)
