#!/usr/bin/env python3
"""Run harness validation only after every final live job has completed."""
import hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
os.sched_setaffinity(0,set(range(64,96)))
names=['final-lanes','final-tcl','final-tcl-planted','final-units','final-supplemental-jobs']
for engine in ('uring','epoll'):
 names += ['final-engine-'+engine,'final-differ-'+engine]
 for mode in ('1s','2s'):names.append('final-debug-'+engine+'-'+mode)
names += ['final-persistence-1s','final-persistence-2s']
until=time.monotonic()+10800
while not all((ROOT/'docs/wave8/jobs'/(n+'.json')).exists() for n in names):
 assert time.monotonic()<until,'live correctness campaign did not finish'
 time.sleep(10)
print('Every live job has a completion receipt; running quiet harness checks.',flush=True)
env=dict(os.environ,LANG='en_US.UTF-8',GATE_TEST_PORT='20098');env.pop('LC_ALL',None)
argv=['python3','tests/gates_test.py'];start=time.time()
log=ROOT/'docs/wave8/gates-test-final73.log';assert not log.exists()
with log.open('w') as f:r=subprocess.run(argv,env=env,stdout=f,stderr=subprocess.STDOUT)
receipt=dict(argv=argv,exit=r.returncode,seconds=time.time()-start,affinity=sorted(os.sched_getaffinity(0)),binary_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest())
(ROOT/'docs/wave8/gates-test-final73.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('gates_test exit',r.returncode,flush=True)
argv=['python3','docs/wave8/run_jobs.py','final-abba-selftest','abba_selftest','--single-slot','--root','build/wave8/selftest-final']
result=subprocess.run(argv,env=env)
raise SystemExit(0 if r.returncode==0 and result.returncode==0 else 1)
