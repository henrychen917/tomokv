#!/usr/bin/env python3
"""Lane correctness jobs only; excludes ABBA, NIC and the full iteration."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'build/pubtrackfix'
def main():
 assert os.sched_getaffinity(0)<=set(range(32,48))
 p=argparse.ArgumentParser();p.add_argument('--stages',default='affected,differ,controls,gates-test');a=p.parse_args()
 stages=a.stages.split(',');cases=[]
 if 'affected' in stages:
  cases.append(('post-affected-final','quick',(ROOT/'docs/pubtrackfix/proof-jobs.txt').read_text(),'build/tomokv','uring'))
 if 'differ' in stages:
  for engine in ('uring','epoll'):
   cases.append(('differ-'+engine,'iteration','differ-split differ-armed','build/tomokv',engine))
 if 'controls' in stages:
  cases.extend([('pre-directed','quick','pubtrackfix','build/pubtrackfix/pre/tomokv','uring'),
                ('pad-directed','quick','pubtrackfix','build/pubtrackfix/pad-a/tomokv','uring')])
  for plant in ('bcast','reply-off','consumer','eviction'):
   cases.append(('plant-'+plant,'quick','redis_tcl','build/pubtrackfix/plants/tomokv-'+plant,'uring'))
 results=[]
 for name,tier,jobs,binary,engine in cases:
  env=os.environ.copy();env.update(REDIS74_ROOT='/home/user/Projects/redis',
   GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',GATE_ONLY_JOBS=jobs,
   GATE_DIFFER_NET_IO=engine,GATE_NET_IO=engine)
  command=['tests/gate.sh',tier,'--server-cores','32-39','--load-cores','40-47',
   '--ports','20310-20399','--candidate-binary',binary]
  log=OUT/('gate-'+name+'.log')
  print('BEGIN',name,flush=True)
  with log.open('w') as f:rc=subprocess.run(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
  results.append(dict(name=name,returncode=rc,command=command,selected_jobs=jobs,engine=engine,log=str(log)))
  (ROOT/'docs/pubtrackfix'/('proof-driver-'+a.stages.replace(',','-')+'.json')).write_text(json.dumps(results,indent=2)+'\n')
  subprocess.run([sys.executable,'docs/pubtrackfix/archive_gate.py',str(log),name],cwd=ROOT,check=True)
  print('END',name,rc,flush=True)
 if 'gates-test' in stages:
  env=os.environ.copy();env['GATE_TEST_PORT']='20309'
  with (OUT/'gates-test-isolated.log').open('w') as f:
   rc=subprocess.run([sys.executable,'tests/gates_test.py'],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
  print('GATES_TEST',rc,flush=True)
if __name__=='__main__':main()
