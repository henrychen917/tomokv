"""Hold a real native accept CQ batch across FLIP entry, without changing a CQE.

The first accepted descriptor is stopped before its generation/pause checks.
Another successful native CQE must already follow it in the same kernel CQ.
After another IO publishes IoDrain, resuming the first descriptor causes the
ordinary retention path to cancel the generation. The next real CQE is stale.
"""
import hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'tests'))
from _lib import Conn,RespError,wait_ready,info
BASE=ROOT/'build/fliplisten/stale';BASE.mkdir(exist_ok=True)
DOC=ROOT/'docs/fliplisten/stale';DOC.mkdir(exist_ok=True)

def run(atomic,outcome,trial):
 name=f'a{atomic}-{outcome}-{trial}'
 out=BASE/name;out.mkdir(exist_ok=True)
 armed,held,stage,events=[out/(x+'.json') for x in ('armed','held','stage','events')]
 for p in (armed,held,stage,events):
  if p.exists():p.unlink()
 script=out/'observe.gdb'
 script.write_text('\n'.join([
  'set pagination off','set confirm off','set non-stop on','set breakpoint pending on',
  'handle SIGPIPE nostop noprint pass','handle SIGTERM nostop noprint pass','python',
  'import json,os',
  'class HoldBatch(gdb.Breakpoint):',
  ' def stop(self):',
  f'  if not os.path.exists({str(armed)!r}):return False',
  "  if int(gdb.parse_and_eval('cqe->res'))<0:return False",
  # Only the administrator exists before the burst. An empty owner cannot be
  # its IO, so that administrator can initiate FLIP while this owner is held.
  "  if int(gdb.parse_and_eval('this->self_->client_count_._M_i'))!=0:return False",
  "  q=gdb.parse_and_eval('this->ring_.r_.cq')",
  "  head=int(q['khead'].dereference());tail=int(q['ktail'].dereference());mask=int(q['kring_mask'].dereference())",
  "  offset=int(gdb.parse_and_eval('this->ring_.raw_callback_index_'))",
  "  generation=int(gdb.parse_and_eval('this->accept_generation_'))",
  '  queued=[]',
  '  for i in range(offset,(tail-head)&0xffffffff):',
  "   c=q['cqes'][(head+i)&mask];tag=int(c['user_data']);fd=int(c['res'])",
  '   if tag>>56==1 and fd>=0 and tag&((1<<48)-1)==generation:queued.append(dict(fd=fd,generation=generation))',
  '  if not queued:return False',
  '  self.enabled=False',
  "  witness=dict(pid=gdb.selected_inferior().pid,thread=gdb.selected_thread().num,tid=int(gdb.parse_and_eval('this->self_->id_')),server=int(gdb.parse_and_eval('this->srv_')),generation=generation,current_fd=int(gdb.parse_and_eval('cqe->res')),queued=queued)",
  f"  with open({str(held)!r},'w') as f:json.dump(witness,f)",
  '  return True',
  "HoldBatch('tomo_db0::IoLoop::on_accept<false, false>')",
  'class Observe(gdb.Breakpoint):',
  ' def stop(self):',
  "  fd=int(gdb.parse_and_eval('cqe->res'))",
  '  if fd>=0:',
  "   old=int(gdb.parse_and_eval('cqe->user_data')) & ((1<<48)-1)",
  "   current=int(gdb.parse_and_eval('this->accept_generation_'))",
  "   state=str(gdb.parse_and_eval('this->srv_->flip_stage_._M_i'))",
  f"   with open({str(events)!r},'a') as f:f.write(json.dumps(dict(fd=fd,old=old,current=current,stage=state))+'\\n')",
  '  return False',
  "Observe('tomo_db0::IoLoop::fliplisten_stale')",
  'class Rollback(gdb.Breakpoint):',
  ' def stop(self):',
  "  if str(gdb.parse_and_eval('stage')).endswith('ExDrain'):",
  *(["   gdb.execute('set var this->srv_->flip_deadline_ns_._M_i = 1')"] if outcome=='rollback' else ['   pass']),
  '  return False',
  "Rollback('tomo_db0::IoLoop::flip_publish_stage')",'end','run'])+'\n')
 argv=['taskset','-c','48-55','gdb','-nx','-q','-x',str(script),'--args',str(ROOT/'build/tomokv'),
       '--port','21800','--bind','127.0.0.1','--dir',str(out),'--save','',
       '--thread-mode','2s','--ratio','6:2','--shards','16','--databases','1',
       '--atomic',str(atomic),'--net-io','uring','--flip-auto','0','--key-lb','0','--client-lb','0']
 (DOC/(name+'.command.json')).write_text(json.dumps(argv,indent=2)+'\n')
 peers=[];pid=None;admin=None;witness=None;reply=None;elapsed=None
 with (out/'server.log').open('w') as log:
  p=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
  def command(text):p.stdin.write((text+'\n').encode());p.stdin.flush()
  try:
   admin=wait_ready('127.0.0.1',21800,timeout=30);admin.sock.settimeout(7)
   children=Path(f'/proc/{p.pid}/task/{p.pid}/children').read_text().split()
   pid=next(int(c) for c in children if Path(f'/proc/{c}/exe').resolve()==ROOT/'build/tomokv')
   before=int(info(admin,'stats')['total_connections_received'])
   armed.write_text('{}\n')
   for _ in range(256):
    c=Conn('127.0.0.1',21800,timeout=7);c.send('PING');peers.append(c)
   deadline=time.monotonic()+1
   while not held.exists() and time.monotonic()<deadline:time.sleep(.01)
   if held.exists():
    witness=json.loads(held.read_text());assert witness['queued']
    start=time.monotonic();admin.send('FLIP',4,4)
    deadline=time.monotonic()+3
    while True:
     if stage.exists():stage.unlink()
     command('python\ns=gdb.Value('+str(witness['server'])+").cast(gdb.lookup_type('tomo_db0::Server').pointer())\n"+
             'with open('+repr(str(stage))+",'w') as f:json.dump(dict(stage=str(s['flip_stage_']['_M_i'])),f)\nend")
     while not stage.exists():
      assert time.monotonic()<deadline,'debugger did not sample the held stage';time.sleep(.005)
     state=json.loads(stage.read_text())['stage']
     if state.endswith('IoDrain'):break
     assert time.monotonic()<deadline,('IoDrain never opened',state);time.sleep(.01)
    witness['held_stage']=state
    # Additional descriptors arrive during the witnessed quiesce.
    for _ in range(24):
     c=Conn('127.0.0.1',21800,timeout=7);c.send('PING');peers.append(c)
    command('continue -a')
    reply=admin.read();elapsed=time.monotonic()-start
    assert elapsed<6.5,elapsed
    assert reply==b'OK' if outcome=='complete' else isinstance(reply,RespError) and b'timed out' in reply.message,reply
   ids=[]
   for c in peers:
    assert c.read()==b'PONG';ids.append(c.must('CLIENT','ID'))
   accepted=int(info(admin,'stats')['total_connections_received'])-before
   observed=[json.loads(l) for l in events.read_text().splitlines()] if events.exists() else []
   assert len(peers)==len(ids)==len(set(ids))==accepted,(len(peers),len(ids),len(set(ids)),accepted)
   if witness:
    expected={x['fd'] for x in witness['queued']}
    assert any(x['fd'] in expected and x['old']==witness['generation'] and x['current']!=x['old'] for x in observed),(witness,observed)
   result=dict(atomic=atomic,outcome=outcome,trial=trial,counts=dict(arrived=len(peers),served=len(ids)),
      errors=[],accepted_delta=accepted,unique_ids=len(set(ids)),positive_stale=observed,witness=witness,
      flips=[dict(reply=repr(reply),seconds=elapsed)] if witness else [],
      sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest())
   (DOC/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
   print(name,len(peers),'served; positive stale',len(observed),flush=True)
   return witness is not None
  finally:
   for c in peers:c.close()
   if admin:admin.close()
   if pid:
    try:os.kill(pid,signal.SIGTERM)
    except ProcessLookupError:pass
   if p.poll() is None:
    try:command('continue -a');time.sleep(.1);command('interrupt -a\nkill inferiors 1\nquit');p.stdin.close();p.wait(timeout=10)
    except (BrokenPipeError,subprocess.TimeoutExpired):
     if pid:
      try:os.kill(pid,signal.SIGKILL)
      except ProcessLookupError:pass
     p.kill();p.wait()
   (DOC/(name+'.server.log')).write_bytes((out/'server.log').read_bytes())
   (DOC/(name+'.gdb')).write_bytes(script.read_bytes())

if __name__=='__main__':
 for p in DOC.glob('a*'):p.unlink()
 for atomic in (0,1):
  for outcome in ('complete','rollback'):
   for trial in range(4):
    deadline=time.monotonic()+10
    while subprocess.check_output(['ss','-ltnH','sport = :21800']).strip():
     assert time.monotonic()<deadline;time.sleep(.05)
    if run(atomic,outcome,trial):break
   else:raise AssertionError(f'no accepted CQ batch in four fresh states: atomic={atomic} outcome={outcome}')
