#!/usr/bin/env python3
"""Exact named-production instruction counts for one quiet fused rotation."""
import concurrent.futures,json,os
from pathlib import Path
import exec1s_scope as s
ROOT=Path(__file__).resolve().parents[1]
def main():
    assert os.sched_getaffinity(0)<=set(range(80,96))
    s.FIXTURE=ROOT/'tests/exec1s_idle_scope.cc'
    for arm in ['X2','X3']:
        s.ARMS['IDLE-'+arm]=s.ARMS[arm]
        for ns in ['normal','db0']:s.build('IDLE-'+arm,ns)
    cases=[('IDLE-'+arm,ns,'IDLE','1s',1,1,-1) for arm in ['X2','X3'] for ns in ['normal','db0']]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:rows=list(pool.map(s.trace,cases))
    pairs=[]
    for ns in ['normal','db0']:
        a=next(r for r in rows if r['arm']=='IDLE-X2' and r['namespace']==ns)
        b=next(r for r in rows if r['arm']=='IDLE-X3' and r['namespace']==ns)
        pairs.append(dict(namespace=ns,x2=a['total'],x3=b['total'],delta=b['total']-a['total'],target_plus_two_pass=b['total']<=a['total']+2))
    s.save(ROOT/'docs/exec1s/idle-counts.json',dict(scope='one actual linked production fused rotation, iterations [2,3), all bells clear; library callees excluded',cases=pairs))
    print(pairs,flush=True)
if __name__=='__main__':main()
