#!/usr/bin/env python3
"""Finish the lane's selected gate jobs serially on its one eight-core slot.

No full iteration or performance job is selected. Each job driver records argv,
locale, affinity, binary hash, exit and the original gate ledger.
"""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0)<=set(range(32,48))
os.environ['LC_ALL']='C'
# The initial uring matrix is launched separately so builds can be inspected.
while not (ROOT/'docs/scriptfix3/jobs/final-uring.json').exists():time.sleep(5)
ordinary=['debug-0','debug-1','feature-split-0','feature-split-1','feature-armed-0','feature-armed-1','script_bounds','notify','differ-split','differ-armed']
plans=[('final-epoll',ordinary,['--engine','epoll'],{}),
       ('final-fused-uring',['debug-0','debug-1','script_bounds','notify'],['--fused'],{}),
       ('final-fused-epoll',['debug-0','debug-1','script_bounds','notify'],['--fused','--engine','epoll'],{})]
for mode in ('1s','2s'):
 for engine in ('uring','epoll'):
  plans.append(('bounds-'+mode+'-'+engine+'-a0',['script_bounds'],['--engine',engine]+(['--fused'] if mode=='1s' else []),{'GATE_TXN_ATOMIC':'0'}))
results=[]
for name,jobs,options,extra in plans:
 argv=['python3','tools/scriptfix3_jobs.py',name,*jobs,*options]
 with (ROOT/'build/scriptfix3'/(name+'-driver.log')).open('w') as log:
  rc=subprocess.run(argv,cwd=ROOT,env=dict(os.environ,**extra),stdout=log,stderr=subprocess.STDOUT).returncode
 results.append(dict(name=name,argv=argv,extra_env=extra,exit=rc))
 (ROOT/'docs/scriptfix3/proof-plan.json').write_text(json.dumps(results,indent=2)+'\n')
 print(name,rc,flush=True)
