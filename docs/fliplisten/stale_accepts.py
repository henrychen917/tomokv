"""Observe real positive old-generation CQEs under churn, without patching the binary."""
import hashlib,json,os,signal,socket,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn,RespError,wait_ready,info
BASE=ROOT/'build/fliplisten/stale';BASE.mkdir(exist_ok=True)
DOC=ROOT/'docs/fliplisten/stale';DOC.mkdir(exist_ok=True)
def run(atomic,trial):
 out=BASE/f'a{atomic}-{trial}';out.mkdir(exist_ok=True)
 events=out/'events.jsonl';script=out/'observe.gdb'
 if events.exists():events.unlink() # every bounded re-roll must observe a fresh process
 script.write_text('\n'.join([
 'set pagination off','set confirm off','set non-stop on','set breakpoint pending on',
 'handle SIGPIPE nostop noprint pass','handle SIGTERM nostop noprint pass','python',
 'import json',
 'class Observe(gdb.Breakpoint):',
 ' def stop(self):',
 "  fd=int(gdb.parse_and_eval('cqe->res'))",
 '  if fd>=0:',
 "   old=int(gdb.parse_and_eval('cqe->user_data')) & ((1<<48)-1)",
 "   current=int(gdb.parse_and_eval('this->accept_generation_'))",
 "   stage=str(gdb.parse_and_eval('this->srv_->flip_stage_._M_i'))",
 f"   with open({str(events)!r},'a') as f:f.write(json.dumps(dict(fd=fd,old=old,current=current,stage=stage))+'\\n')",
 '  return False',
 "Observe('tomo_db0::IoLoop::fliplisten_stale')",
 'class Rollback(gdb.Breakpoint):',
 ' count=0',
 ' def stop(self):',
 "  if not str(gdb.parse_and_eval('stage')).endswith('ExDrain'):return False",
 '  self.count+=1',
 "  if self.count%2==0:gdb.execute('set var this->srv_->flip_deadline_ns_._M_i = 1')",
 '  return False',
 "Rollback('tomo_db0::IoLoop::flip_publish_stage')",
 'end','run'])+'\n')
 argv=['taskset','-c','48-55','gdb','-nx','-q','-x',str(script),'--args',str(ROOT/'build/tomokv'),
       '--port','21800','--bind','127.0.0.1','--dir',str(out),'--save','',
       '--thread-mode','2s','--ratio','6:2','--shards','16','--databases','1',
       '--atomic',str(atomic),'--net-io','uring','--flip-auto','0','--key-lb','0','--client-lb','0']
 (out/'command.json').write_text(json.dumps(argv)+'\n')
 counts={'arrived':0,'served':0};ids=set();errors=[];stop=threading.Event();lock=threading.Lock();flips=[]
 with (out/'server.log').open('w') as log:
  p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
  pid=None;workers=[];admin=None
  try:
   admin=wait_ready('127.0.0.1',21800,timeout=30)
   children=Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
   pid=next(int(c) for c in children if Path(f'/proc/{c}/exe').resolve()==ROOT/'build/tomokv')
   before=int(info(admin,'stats')['total_connections_received'])
   def worker():
    while not stop.is_set():
     peer=None
     try:
      peer=Conn('127.0.0.1',21800,timeout=7)
      with lock:counts['arrived']+=1
      assert peer.must('PING')==b'PONG'
      ident=peer.must('CLIENT','ID')
      with lock:
       assert ident not in ids
       ids.add(ident);counts['served']+=1
     except Exception as error:
      with lock:errors.append(repr(error))
      stop.set()
     finally:
      if peer:peer.close()
   workers=[threading.Thread(target=worker) for _ in range(24)]
   for w in workers:w.start()
   for i in range(24):
    live=dict(zip(*(iter(admin.must('FLIP')),)*2))[b'live_io']
    target=4 if live!=4 else 6
    start=time.monotonic();reply=admin.cmd('FLIP',target,8-target)
    elapsed=time.monotonic()-start
    assert reply==b'OK' or isinstance(reply,RespError) and b'timed out' in reply.message,reply
    assert elapsed<6.5,elapsed
    flips.append(dict(reply=repr(reply),seconds=elapsed))
    if errors:break
    time.sleep(.01)
   stop.set()
   for w in workers:w.join(8)
   assert not any(w.is_alive() for w in workers)
   after=int(info(admin,'stats')['total_connections_received'])
   observed=[json.loads(l) for l in events.read_text().splitlines()] if events.exists() else []
   result=dict(atomic=atomic,trial=trial,counts=counts,errors=errors,accepted_delta=after-before,
               sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest(),
               unique_ids=len(ids),positive_stale=observed,flips=flips)
   assert not errors and counts['arrived']==counts['served']==len(ids)==after-before,result
   assert any(x['old']!=x['current'] for x in observed) or not observed,result
   assert any(x['reply']=="b'OK'" for x in flips) and any('timed out' in x['reply'] for x in flips),flips
   (DOC/f'a{atomic}-{trial}.json').write_text(json.dumps(result,indent=2)+'\n')
   print(atomic,trial,counts,'positive stale',len(observed),flush=True)
   return bool(observed)
  finally:
   stop.set()
   for w in workers:w.join(8)
   if admin:admin.close()
   if pid:
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:pass
    deadline=time.monotonic()+8
    while Path(f'/proc/{pid}').exists() and time.monotonic()<deadline:time.sleep(.02)
   if p.poll() is None:
    try:p.stdin.write(b'interrupt -a\nkill inferiors 1\nquit\n');p.stdin.close();p.wait(timeout=10)
    except (BrokenPipeError,subprocess.TimeoutExpired):p.kill();p.wait()
   (DOC/f'a{atomic}-{trial}.server.log').write_text((out/'server.log').read_text(errors='replace'))
   if events.exists():(DOC/f'a{atomic}-{trial}.events.jsonl').write_bytes(events.read_bytes())
if __name__=='__main__':
 for atomic in (0,1):
  for trial in range(4):
   deadline=time.monotonic()+10
   while subprocess.check_output(['ss','-ltnH','sport = :21800']).strip():
    assert time.monotonic()<deadline;time.sleep(.05)
   if run(atomic,trial):break
  else:raise AssertionError(f'no positive old-generation CQE witnessed in four fresh states: atomic {atomic}')
