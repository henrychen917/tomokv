#!/usr/bin/env python3
"""Audit declared whole-job coverage, retaining each unsuccessful attempt."""
import hashlib, json, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave11'
sys.path.insert(0,str(DOC))
from collect_jobs import collect
os.sched_setaffinity(0,set(range(64,96)))
sha=hashlib.sha256((ROOT/'build/wave11/tomokv-POST').read_bytes()).hexdigest()
matrix=json.loads((DOC/'correctness-matrix.json').read_text())
runs=collect()['runs']; requirements=[]
for category in ('once','new_lanes_once','tcl'):
    requirements += [(name,None,None,None) for name in matrix[category]]
for engine in ('uring','epoll'):
    requirements += [(name,None,engine,None) for name in matrix['each_engine']+matrix['differ_each_engine']]
for mode in ('0','1'):
    requirements += [(name,mode,None,None) for name in matrix['each_mode']]
    for engine in ('uring','epoll'):
        requirements += [(name,mode,engine,None) for name in matrix['each_mode_engine']]
        requirements += [(name,mode,engine,'0') for name in matrix['script_bounds_atomic0_each_mode_engine']]
requirements=list(dict.fromkeys(requirements))
results=[]
for name,mode,engine,atomic in requirements:
    attempts=[]
    children=([name+'-0',name+'-1']+(['differ-equivalence'] if name=='differ-split' else [])
              if name in ('differ-split','differ-armed') else [name])
    for run in runs:
        if run['binary_sha256']!=sha:continue
        env=run['env']
        if mode is not None and env['GATE_TXN_FUSED']!=mode:continue
        if engine is not None and env['GATE_NET_IO']!=engine:continue
        if atomic is not None and env.get('GATE_TXN_ATOMIC')!=atomic:continue
        selected=[j for j in run['jobs'] if j['name'] in children]
        if selected:
            complete=len(selected)==len(children) and all(j['complete'] for j in selected)
            attempts.append(dict(run=run['name'],complete=complete,
                passed=sum(j.get('passed',0) for j in selected),
                failed=sum(j.get('failed',0) for j in selected),
                exit=max(j.get('exit',1) for j in selected),children=children))
    passed=any(a['complete'] and a['exit']==0 and a['failed']==0 for a in attempts)
    results.append(dict(job=name,mode=mode,engine=engine,atomic=atomic,passed=passed,attempts=attempts))
failures=[dict(run=r['name'],job=j['name'],failed=j.get('failed'),exit=j.get('exit'))
          for r in runs if r['binary_sha256']==sha for j in r['jobs']
          if j.get('failed',0) or j.get('exit',0)]
result=dict(binary_sha256=sha,requirements=results,passed=sum(r['passed'] for r in results),
    total=len(results),uncovered=[r for r in results if not r['passed']],all_failures=failures,
    note='Coverage accepts a complete successful whole-job replay and retains every failed attempt. '
         'Standalone Python/flushmerit self-tests and throwaway ABBA are separately bound receipts.')
(DOC/'correctness-coverage.json').write_text(json.dumps(result,indent=2)+'\n')
(DOC/'correctness-jobs.json').write_text(json.dumps(dict(runs=runs),indent=2)+'\n')
print(result['passed'],'/',result['total'],'whole-job geometry requirements')
print('uncovered:',[(r['job'],r['mode'],r['engine'],r['atomic']) for r in result['uncovered']])
