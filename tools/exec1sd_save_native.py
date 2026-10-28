#!/usr/bin/env python3
"""Bounded, unchanged psfix seed-22 rerolls on native frozen servers."""
import argparse,json,os,subprocess
from pathlib import Path
import exec1sd as d
from exec1sd_save import ready,stop
assert os.sched_getaffinity(0)<=set(range(64,96))
p=argparse.ArgumentParser();p.add_argument('arm');p.add_argument('--repeats',type=int,default=128);a=p.parse_args()
arm=next(r for r in json.loads((d.DOCS/'arms.json').read_text()) if r['arm']==a.arm)
assert d.sha(arm['binary'])==arm['sha256']
out=d.OUT/('save-native-'+a.arm);out.mkdir(exist_ok=False)
commands=[];processes=[];rows=[]
try:
 for label,binary,cpus,port in [('oracle','/home/user/Projects/redis/src/redis-server','72-79',20001),('target',arm['binary'],'64-71',20000)]:
  directory=out/label;directory.mkdir()
  command=['taskset','-c',cpus,binary,'--port',str(port),'--bind','127.0.0.1','--save','','--dir',str(directory),'--enable-debug-command','yes']
  command+=['--shards','16','--ratio','6:2','--net-io','epoll','--databases','16','--atomic','0'] if label=='target' else ['--appendonly','no']
  commands.append(command)
  with (out/(label+'.log')).open('w') as stream:process=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
  processes.append(process);ready(port,process)
 for repeat in range(a.repeats):
  log=out/(str(repeat)+'.log');command=['taskset','-c','80-95','python3','tests/differ.py','127.0.0.1','20000','127.0.0.1','20001','psfix','22']
  with log.open('w') as stream:result=subprocess.run(command,stdout=stream,stderr=subprocess.STDOUT,timeout=180)
  rows.append(dict(repeat=repeat,returncode=result.returncode,log=str(log),sha256=d.sha(log)))
  print(a.arm,repeat,result.returncode,flush=True)
  if result.returncode:break
finally:
 for process in reversed(processes):stop(process)
 d.save(d.DOCS/('save-native-'+a.arm+'.json'),dict(arm=arm,commands=commands,seed=22,suite='psfix',mode='2s',atomic=0,engine='epoll',results=rows))
