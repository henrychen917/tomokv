#!/usr/bin/env python3
"""Finish required correctness receipts on the final binary, serially on lane CPUs."""
import json, os, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.sched_setaffinity(0,set(range(32,48)))
os.chdir(ROOT)
# Other already-started receipts own their processes; never interfere with them.
for name in ('frozen-units','final-roots'):
    while not (ROOT/'docs/multifix/jobs'/f'{name}.json').exists():
        time.sleep(10)
while not (ROOT/'docs/multifix/instructions/results-final.json').exists():
    time.sleep(10)
rows=[]
def run(name,argv,env=None):
    print('START',name,flush=True)
    start=time.time()
    with (ROOT/'build/multifix'/f'{name}-driver.log').open('w') as out:
        result=subprocess.run(argv,env=env,stdout=out,stderr=subprocess.STDOUT)
    rows.append(dict(name=name,argv=argv,exit=result.returncode,seconds=time.time()-start))
    (ROOT/'docs/multifix/verification-stages.json').write_text(json.dumps(rows,indent=2)+'\n')
    print('DONE',name,result.returncode,flush=True)
    return result.returncode
if run('required-freshness',['python3','docs/multifix/freshness.py','--build']):
    raise SystemExit('required build freshness failed; inspect before consuming witnesses')
env=dict(os.environ,GATE_TEST_PORT='20598')
run('final-gates-test',['python3','tests/gates_test.py'],env)
def jobs(name,names,engine='uring',port=20550):
    return run(name,['python3','docs/multifix/run_jobs.py',name,*names,
                    '--single-slot','--binary','build/multifix/tomokv-post',
                    '--engine',engine,'--port',str(port)])
jobs('final-affected',['compat2','clientfix','atomfix5_watch','atomfix5_accounting','moverfix',
    'txn_group_fused','txn_group_split','txnorder-fused-0','txnorder-fused-1',
    'txnorder-split-0','txnorder-split-1','txnorder2','txnorder_wake','txnorder_index',
    'script_bounds','scriptfix','lualibs','serverfix_slowlog','notify','notifycompat','notify_order',
    'atomic_units','core_units','climonfix','racefix_climon','fused-0','fused-1','release_batteries'])
for engine in ('uring','epoll'):
    jobs('final-differ-'+engine,['differ-split-0','differ-split-1','differ-armed-0',
         'differ-armed-1','differ-equivalence'],engine,20570)
run('final-planted-tcl',['python3','docs/multifix/run_jobs.py','final-planted-tcl','redis_tcl',
    '--single-slot','--binary','build/multifix/tomokv-regression','--port','20580'])
jobs('final-instrument-controls',['abba_selftest'],port=20580)
run('final-wire',['python3','docs/multifix/reproduce.py','--binary','build/multifix/tomokv-post',
                  '--output','docs/multifix/final-wire','--port','20500'])
run('last-freshness',['python3','docs/multifix/freshness.py'])
