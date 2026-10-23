"""Force the shared retry flag at a new epoch; keep a broken-binary control.

This schedules the flag state of a borrowed-listener SQ retry at the next
IoDrain entry. It does not claim to make the kernel submission queue fill.
The previous completed FLIP supplies real transferred listeners/cancel fences.
"""
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn,wait_ready,info

def run(binary,label,atomic,expect_pass):
 out=ROOT/'build/fliplisten/retry-epoch'/f'{label}-a{atomic}'
 out.mkdir(parents=True,exist_ok=False)
 witness=out/'witness.json';script=out/'force.gdb'
 script.write_text('\n'.join([
  'set pagination off','set confirm off','set non-stop on','set breakpoint pending on',
  'handle SIGPIPE nostop noprint pass','handle SIGTERM nostop noprint pass','python',
  'import json',
  'class Force(gdb.Breakpoint):',
  ' def stop(self):',
  "  if int(gdb.parse_and_eval('this->srv_->flip_epoch_._M_i'))!=2:return False",
  "  tid=int(gdb.parse_and_eval('this->self_->id_'))",
  "  ls=gdb.parse_and_eval('this->srv_->flip_listeners_._M_ptr->listeners._M_elems')",
  "  borrowed=[i for i in range(384) if int(ls[i]['fd'])>=0 and int(ls[i]['owner'])==tid and int(ls[i]['home'])!=tid]",
  '  if not borrowed:return False',
  '  self.enabled=False',
  "  gdb.execute('set var this->accept_quiescing_ = true')",
  "  gdb.execute('set var this->accept_pending_ = true')",
  f"  with open({str(witness)!r},'w') as f:json.dump(dict(pid=gdb.selected_inferior().pid,tid=tid,borrowed=borrowed,old_cancel_fences=[bool(ls[i]['cancel_submitted']) for i in borrowed]),f)",
  '  return False',
  "Force('tomo_db0::IoLoop::fliplisten_quiesce')",'end','run'])+'\n')
 argv=['taskset','-c','48-55','gdb','-nx','-q','-x',str(script),'--args',str(binary),
       '--port','21860','--bind','127.0.0.1','--dir',str(out),'--save','',
       '--thread-mode','2s','--ratio','6:2','--shards','16','--databases','1',
       '--atomic',str(atomic),'--net-io','uring','--flip-auto','0','--key-lb','0','--client-lb','0']
 result=dict(arm=label,atomic=atomic,argv=argv,sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
 pid=None;admin=None;peers=[]
 with (out/'server.log').open('w') as log:
  p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
  try:
   admin=wait_ready('127.0.0.1',21860,timeout=30);admin.sock.settimeout(8)
   children=Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
   pid=next(int(c) for c in children if Path(f'/proc/{c}/exe').resolve()==binary.resolve())
   assert admin.must('FLIP',4,4)==b'OK'
   start=time.monotonic()
   try:reply=admin.cmd('FLIP',6,2);result['reply']=repr(reply)
   except TimeoutError:reply=None;result['reply']='socket deadline after 8 seconds'
   result['seconds']=time.monotonic()-start
   assert witness.exists(),'forced retry window never opened'
   result['witness']=json.loads(witness.read_text())
   assert result['witness']['borrowed'] and all(result['witness']['old_cancel_fences'])
   result['passed']=reply==b'OK' and result['seconds']<6.5
   if result['passed']:
    before=int(info(admin,'stats')['total_connections_received'])
    ids=[]
    for _ in range(64):
     c=Conn('127.0.0.1',21860,timeout=8);peers.append(c)
     assert c.must('PING')==b'PONG';ids.append(c.must('CLIENT','ID'))
    result['served']=len(ids);result['unique_ids']=len(set(ids))
    result['accepted_delta']=int(info(admin,'stats')['total_connections_received'])-before
    assert len(ids)==len(set(ids))==result['accepted_delta']==64
   assert result['passed']==expect_pass,result
  finally:
   for c in peers:c.close()
   if admin:admin.close()
   if pid:
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:pass
    deadline=time.monotonic()+1
    while Path(f'/proc/{pid}').exists() and time.monotonic()<deadline:time.sleep(.02)
   if p.poll() is None:
    try:p.stdin.write(b'interrupt -a\nkill inferiors 1\nquit\n');p.stdin.close();p.wait(timeout=10)
    except (BrokenPipeError,subprocess.TimeoutExpired):
     if pid:
      try:os.kill(pid,signal.SIGKILL)
      except ProcessLookupError:pass
     p.kill();p.wait()
   dest=ROOT/'docs/fliplisten/retry-epoch';dest.mkdir(exist_ok=True)
   (dest/f'{label}-a{atomic}.json').write_text(json.dumps(result,indent=2)+'\n')
   (dest/f'{label}-a{atomic}.server.log').write_bytes((out/'server.log').read_bytes())
 print(label,atomic,result['reply'],result['seconds'],flush=True)

if __name__=='__main__':
 label=sys.argv[1]
 binary=ROOT/'build'/('tomokv' if label=='POST' else 'tomokv-before-retry-fix')
 for atomic in (0,1):
  deadline=time.monotonic()+10
  while subprocess.check_output(['ss','-ltnH','sport = :21860']).strip():
   assert time.monotonic()<deadline;time.sleep(.05)
  run(binary,label,atomic,label=='POST')
