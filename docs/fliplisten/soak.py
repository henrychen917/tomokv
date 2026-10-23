"""Two-minute value-verified FLIP/churn soak per engine, with flip-auto=1."""
import hashlib,json,os,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn,RespError,info,wait_ready
os.sched_setaffinity(0,set(range(56,64)))
rows=[]
for engine in ('uring','epoll'):
 out=ROOT/'build/fliplisten/soak'/engine;out.mkdir(parents=True,exist_ok=True)
 dest=ROOT/'docs/fliplisten/soak'/engine;dest.mkdir(parents=True,exist_ok=True)
 argv=['taskset','-c','48-55',str(ROOT/'build/tomokv'),'--port','21860',
       '--bind','127.0.0.1','--dir',str(out),'--save','','--thread-mode','2s',
       '--ratio','6:2','--shards','16','--atomic','1','--net-io',engine,'--flip-auto','1']
 (dest/'command.json').write_text(json.dumps(dict(server=argv,seconds=120,load_cores='56-63',
    sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest()),indent=2)+'\n')
 stop=threading.Event();lock=threading.Lock();errors=[];ids=set();counts=dict(arrived=0,served=0)
 progress=[0]*8;flips=[];threads=[];admin=None
 def connect():
  c=Conn('127.0.0.1',21860,timeout=8)
  with lock:counts['arrived']+=1
  assert c.must('PING')==b'PONG'
  ident=c.must('CLIENT','ID')
  with lock:
   assert ident not in ids,ident
   ids.add(ident);counts['served']+=1
  return c
 def churn():
  while not stop.is_set():
   c=None
   try:c=connect()
   except Exception as error:
    with lock:errors.append(repr(error))
    stop.set()
   finally:
    if c:c.close()
   stop.wait(.02)
 def values(index):
  c=None
  try:
   c=connect();keys=[f'soak:{index}:{k}' for k in range(8)]
   generation=0
   while not stop.is_set():
    generation+=1
    expected=[f'{k}:{generation}'.encode() for k in keys]
    args=[v for pair in zip(keys,expected) for v in pair]
    assert c.must('MSET',*args)==b'OK'
    assert c.must('MGET',*keys)==expected,(index,generation)
    with lock:progress[index]+=1
    stop.wait(.002)
  except Exception as error:
   with lock:errors.append(repr(error))
   stop.set()
  finally:
   if c:c.close()
 with (dest/'server.log').open('w') as log:
  p=subprocess.Popen(argv,stdout=log,stderr=subprocess.STDOUT)
  try:
   admin=wait_ready('127.0.0.1',21860,timeout=30);admin.sock.settimeout(8)
   before=info(admin);started=time.monotonic()
   threads=[threading.Thread(target=values,args=(i,)) for i in range(8)]
   threads += [threading.Thread(target=churn) for _ in range(6)]
   for t in threads:t.start()
   while time.monotonic()-started<120 and not stop.is_set():
    state=admin.must('FLIP');state=dict(zip(state[::2],state[1::2]))
    target=4 if state[b'live_io']!=4 else 6
    start=time.monotonic();reply=admin.cmd('FLIP',target,8-target)
    elapsed=time.monotonic()-start
    assert reply==b'OK' or isinstance(reply,RespError) and reply.message==b'ERR a FLIP is already in progress',reply
    assert elapsed<6.5,elapsed
    flips.append(dict(reply=repr(reply),seconds=elapsed))
    stop.wait(.25)
   seconds=time.monotonic()-started;stop.set()
   for t in threads:t.join(9)
   assert not any(t.is_alive() for t in threads)
   assert not errors and all(progress) and seconds>=120,(errors,progress,seconds)
   after=info(admin)
   accepted=int(after['total_connections_received'])-int(before['total_connections_received'])
   completed=int(after['flip_completed'])-int(before['flip_completed'])
   manual=sum(f['reply']=="b'OK'" for f in flips)
   assert counts['arrived']==counts['served']==len(ids)==accepted and accepted>8,counts
   assert completed>=manual>0,(completed,manual)
   result=dict(engine=engine,seconds=seconds,atomic=1,flip_auto=1,counts=counts,
      accepted_delta=accepted,unique_ids=len(ids),value_rounds=progress,errors=errors,
      completed_flips=completed,manual_completed_flips=manual,flips=flips)
   (dest/'result.json').write_text(json.dumps(result,indent=2)+'\n')
  finally:
   stop.set()
   for t in threads:t.join(9)
   if admin:admin.close()
   p.terminate()
   try:p.wait(timeout=15)
   except subprocess.TimeoutExpired:p.kill();p.wait();raise
  rows.append(dict(engine=engine,server_returncode=p.returncode,seconds=seconds,
      arrived=accepted,completed_flips=completed,manual_completed_flips=manual))
  assert p.returncode==0,rows
  print(rows[-1],flush=True)
(ROOT/'docs/fliplisten/soak/results.json').write_text(json.dumps(rows,indent=2)+'\n')
