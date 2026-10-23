set pagination off
set confirm off
set non-stop on
set breakpoint pending on
handle SIGPIPE nostop noprint pass
handle SIGTERM nostop noprint pass
python
import json,os
class HoldBatch(gdb.Breakpoint):
 def stop(self):
  if not os.path.exists('/home/user/Projects/cx-fliplisten/build/fliplisten/stale/a1-complete-0/armed.json'):return False
  if int(gdb.parse_and_eval('cqe->res'))<0:return False
  if int(gdb.parse_and_eval('this->self_->client_count_._M_i'))!=0:return False
  q=gdb.parse_and_eval('this->ring_.r_.cq')
  head=int(q['khead'].dereference());tail=int(q['ktail'].dereference());mask=int(q['kring_mask'].dereference())
  offset=int(gdb.parse_and_eval('this->ring_.raw_callback_index_'))
  generation=int(gdb.parse_and_eval('this->accept_generation_'))
  queued=[]
  for i in range(offset,(tail-head)&0xffffffff):
   c=q['cqes'][(head+i)&mask];tag=int(c['user_data']);fd=int(c['res'])
   if tag>>56==1 and fd>=0 and tag&((1<<48)-1)==generation:queued.append(dict(fd=fd,generation=generation))
  if not queued:return False
  self.enabled=False
  witness=dict(pid=gdb.selected_inferior().pid,thread=gdb.selected_thread().num,tid=int(gdb.parse_and_eval('this->self_->id_')),server=int(gdb.parse_and_eval('this->srv_')),generation=generation,current_fd=int(gdb.parse_and_eval('cqe->res')),queued=queued)
  with open('/home/user/Projects/cx-fliplisten/build/fliplisten/stale/a1-complete-0/held.json','w') as f:json.dump(witness,f)
  return True
HoldBatch('tomo_db0::IoLoop::on_accept<false, false>')
class Observe(gdb.Breakpoint):
 def stop(self):
  fd=int(gdb.parse_and_eval('cqe->res'))
  if fd>=0:
   old=int(gdb.parse_and_eval('cqe->user_data')) & ((1<<48)-1)
   current=int(gdb.parse_and_eval('this->accept_generation_'))
   state=str(gdb.parse_and_eval('this->srv_->flip_stage_._M_i'))
   with open('/home/user/Projects/cx-fliplisten/build/fliplisten/stale/a1-complete-0/events.json','a') as f:f.write(json.dumps(dict(fd=fd,old=old,current=current,stage=state))+'\n')
  return False
Observe('tomo_db0::IoLoop::fliplisten_stale')
class Rollback(gdb.Breakpoint):
 def stop(self):
  if str(gdb.parse_and_eval('stage')).endswith('ExDrain'):
   pass
  return False
Rollback('tomo_db0::IoLoop::flip_publish_stage')
end
run
