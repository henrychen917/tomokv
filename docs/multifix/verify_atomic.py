#!/usr/bin/env python3
"""Run the gate's MVCC batteries with its explicit correctness-only switch."""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT);os.sched_setaffinity(0,set(range(32,48)))
progress=ROOT/'docs/multifix/verification-stages.json'
while not progress.exists() or not any(r['name']=='last-freshness' for r in json.loads(progress.read_text())):
    time.sleep(10)
assert next(r for r in json.loads(progress.read_text()) if r['name']=='last-freshness')['exit']==0
results=[]
for engine in ('uring','epoll'):
    for mode in ('1s','2s'):
        name=f'final-atomic-{mode}-{engine}'
        argv=['python3','docs/multifix/run_jobs.py',name,'atomic_batteries','--single-slot',
              '--binary','build/multifix/tomokv-post','--port','20500','--engine',engine]
        if mode=='1s':argv.append('--fused')
        with (ROOT/'build/multifix'/f'{name}-driver.log').open('w') as out:
            result=subprocess.run(argv,env=dict(os.environ,GATE_PROOF_NO_RATES='1'),stdout=out,stderr=subprocess.STDOUT)
        results.append(dict(name=name,exit=result.returncode,argv=argv))
        (ROOT/'docs/multifix/atomic-stages.json').write_text(json.dumps(results,indent=2)+'\n')
        print(name,result.returncode,flush=True)
raise SystemExit(int(any(r['exit'] for r in results)))
