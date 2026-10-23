set pagination off
set confirm off
set non-stop on
set breakpoint pending on
handle SIGPIPE nostop noprint pass
handle SIGTERM nostop noprint pass
python
import json,time
class HoldCancel(gdb.Breakpoint):
 def stop(self):
  epoch=int(gdb.parse_and_eval('this->srv_->flip_epoch_._M_i'))
  tid=int(gdb.parse_and_eval('this->self_->id_'))
  armed=bool(gdb.parse_and_eval('this->accept_armed_'))
  if not armed:return False
  self.enabled=False
  time.sleep(.05)
  q=gdb.parse_and_eval('this->ring_.r_.cq')
  head=int(q['khead'].dereference());tail=int(q['ktail'].dereference());mask=int(q['kring_mask'].dereference())
  offset=int(gdb.parse_and_eval('this->ring_.raw_callback_index_')) if bool(gdb.parse_and_eval('this->ring_.raw_callback_active_')) else 0
  queued=[]
  for i in range(offset,(tail-head)&0xffffffff):
   c=q['cqes'][(head+i)&mask];tag=int(c['user_data']);fd=int(c['res'])
   if tag>>56==1 and fd>=0:queued.append(dict(fd=fd,generation=tag&((1<<48)-1)))
  with open('/home/user/Projects/cx-fliplisten/build/fliplisten/stale/a0-0/windows.jsonl','a') as f:f.write(json.dumps(dict(epoch=epoch,tid=tid,native_armed=armed,hold_s=.05,queued=queued))+'\n')
  return False
HoldCancel('tomo_db0::IoLoop::fliplisten_quiesce')
class Observe(gdb.Breakpoint):
 def stop(self):
  fd=int(gdb.parse_and_eval('cqe->res'))
  if fd>=0:
   old=int(gdb.parse_and_eval('cqe->user_data')) & ((1<<48)-1)
   current=int(gdb.parse_and_eval('this->accept_generation_'))
   stage=str(gdb.parse_and_eval('this->srv_->flip_stage_._M_i'))
   with open('/home/user/Projects/cx-fliplisten/build/fliplisten/stale/a0-0/events.jsonl','a') as f:f.write(json.dumps(dict(fd=fd,old=old,current=current,stage=stage))+'\n')
  return False
Observe('tomo_db0::IoLoop::fliplisten_stale')
class Rollback(gdb.Breakpoint):
 count=0
 def stop(self):
  if not str(gdb.parse_and_eval('stage')).endswith('ExDrain'):return False
  self.count+=1
  if self.count%2==0:gdb.execute('set var this->srv_->flip_deadline_ns_._M_i = 1')
  return False
Rollback('tomo_db0::IoLoop::flip_publish_stage')
end
run
