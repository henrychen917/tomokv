#!/usr/bin/env python3
"""Bounded, unchanged psfix seed-22 rerolls on native frozen servers."""
import argparse,ctypes,fcntl,json,os,subprocess
from pathlib import Path
import exec1sd as d
from exec1sd_save import ready,stop
assert os.sched_getaffinity(0)<=set(range(64,96))
port_lock=(d.OUT/'save-native-ports.lock').open('w')
fcntl.flock(port_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
p=argparse.ArgumentParser();p.add_argument('arm');p.add_argument('--repeats',type=int,default=128);p.add_argument('--inspect',action='store_true');p.add_argument('--label',default='');a=p.parse_args()
arm=next(r for r in json.loads((d.DOCS/'arms.json').read_text()) if r['arm']==a.arm)
assert d.sha(arm['binary'])==arm['sha256']
receipt_label='save-native-'+a.arm+('-inspect-live' if a.inspect else '')+a.label
out=d.OUT/receipt_label;out.mkdir(exist_ok=False)
commands=[];processes=[];rows=[]
def inspect():
 script=out/'hang.gdb'
 script.write_text('''set pagination off
set print elements 6
set print thread-events off
thread apply all bt 8
python
import gdb,json
fields={}
for key in ['phase_','epoch_','executor_count_','ready_owners_','frozen_owners_','marked_owners_','finished_owners_','writer_tid_','io_inflight_']:
 try:fields[key]=str(gdb.parse_and_eval('tomo::g_server->snapshot_.'+key))
 except Exception as e:fields[key]=str(e)
print('SAVE_HANG '+json.dumps(fields))
for thread in gdb.selected_inferior().threads():
 thread.switch();frame=gdb.newest_frame()
 while frame:
  if 'ExLoopT<false>::run' in (frame.name() or ''):
   frame.select();fields={'thread':thread.num}
   for key in ['snapshot_owner_state_','snapshot_epoch_','snapshot_prepare_cursor_','snapshot_progress_cursor_','snapshot_was_cancelled_','snapshot_manager_','self_->id_'] + ['snapshot_manager_->'+x for x in ['phase_','epoch_','executor_count_','ready_owners_','frozen_owners_','marked_owners_','finished_owners_','writer_tid_','io_inflight_','save_current_shard_']]:
    try:fields[key]=str(gdb.parse_and_eval(key))
    except Exception as e:fields[key]=str(e)
   print('SAVE_OWNER '+json.dumps(fields))
  frame=frame.older()
end
detach
''')
 with (out/'hang.log').open('w') as stream:
  subprocess.run(['taskset','-c','80-95','gdb','-nx','-batch','-p',str(processes[-1].pid),'-x',str(script)],stdout=stream,stderr=subprocess.STDOUT,timeout=30)
try:
 for label,binary,cpus,port in [('oracle','/home/user/Projects/redis/src/redis-server','72-79',20001),('target',arm['binary'],'64-71',20000)]:
  directory=out/label;directory.mkdir()
  command=['taskset','-c',cpus,binary,'--port',str(port),'--bind','127.0.0.1','--save','','--dir',str(directory),'--enable-debug-command','yes']
  command+=['--shards','16','--ratio','6:2','--net-io','epoll','--databases','16','--atomic','0'] if label=='target' else ['--appendonly','no']
  commands.append(command)
  with (out/(label+'.log')).open('w') as stream:process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True,
   preexec_fn=(lambda:ctypes.CDLL(None).prctl(0x59616d61,-1,0,0,0)) if a.inspect and label=='target' else None)
  processes.append(process);ready(port,process)
 for repeat in range(a.repeats):
  log=out/(str(repeat)+'.log');command=['taskset','-c','80-95','python3','tests/differ.py','127.0.0.1','20000','127.0.0.1','20001','psfix','22']
  with log.open('w') as stream:
   result=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)
   try:result.wait(timeout=10 if a.inspect else 180)
   except subprocess.TimeoutExpired:
    if a.inspect:inspect()
    result.wait(timeout=180)
  rows.append(dict(repeat=repeat,returncode=result.returncode,log=str(log),sha256=d.sha(log)))
  print(a.arm,repeat,result.returncode,flush=True)
  if result.returncode:break
finally:
 for process in reversed(processes):stop(process)
 d.save(d.DOCS/(receipt_label+'.json'),dict(arm=arm,commands=commands,seed=22,suite='psfix',mode='2s',atomic=0,engine='epoll',results=rows))
