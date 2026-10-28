#!/usr/bin/env python3
"""Run time-sensitive failed jobs after this lane's other verification finishes."""
import hashlib,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT)
os.sched_setaffinity(0,set(range(96,112)))
DOC=ROOT/'docs/streamfix'
waiting=['final-main','final-directed','final-differ-uring','final-differ-epoll']
while not all((DOC/'jobs'/(name+'.json')).exists() for name in waiting):time.sleep(5)
receipt=dict(waited_for=waiting,affinity=sorted(os.sched_getaffinity(0)),checks=[])
started=time.time()
with (DOC/'gates-test-quiet.log').open('w') as log:
    command=['python3','tests/gates_test.py']
    r=subprocess.run(command,env=dict(os.environ,GATE_TEST_PORT='20698'),stdout=log,stderr=subprocess.STDOUT)
receipt['checks'].append(dict(command=command,exit=r.returncode,seconds=time.time()-started))
# The complete owning job, including both modes; no test-name filter or tolerance override.
command=['python3','docs/streamfix/run_jobs.py','final-quiet-recheck','abba_selftest','redis_tcl','feature-split-0','feature-split-1','feature-armed-0','feature-armed-1','--binary','build/streamfix/post-final/tomokv','--port','20680']
with (DOC/'final-quiet-driver.log').open('w') as log:
    r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
receipt['checks'].append(dict(command=command,exit=r.returncode))
(DOC/'quiet-rechecks.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
raise SystemExit(any(row['exit'] for row in receipt['checks']))
