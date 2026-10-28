#!/usr/bin/env python3
"""Reduced re-proof: 48 ordinary scopes per PRE/POST/PAD-A, relevant lever scopes."""
import concurrent.futures
import json
import os
from pathlib import Path
import exec1s_scope as s

ROOT=Path(__file__).resolve().parents[1]

def main():
    assert os.sched_getaffinity(0)<=set(range(48,64))
    ordinary=[(arm,ns,command,mode,batch,atomic,-1)
              for arm in ('PRE','POST','PAD-A') for ns in ('normal','db0')
              for command in ('GET','SET','INCR','MGET','MSET') for mode in ('1s','2s')
              for batch in (1,32) for atomic in ((0,1) if command=='MSET' else (1,))]
    levers=[]
    for arm in ('PRE','POST','X1','X2'):
        levers += [('OWNER-'+arm,ns,'EXEC',mode,8,1,-1) for ns in ('normal','db0') for mode in ('1s','2s')]
    for arm in ('PRE','POST','X3','X4','X5'):
        levers += [('IO-'+arm,ns,'EXEC',mode,1,1,-1) for ns in ('normal','db0') for mode in ('1s','2s')]
    for arm in ('X3','X4'):
        levers += [('IO-'+arm,ns,'WB',mode,1,1,1 if arm=='X4' else -1)
                   for ns in ('normal','db0') for mode in ('1s','2s')]
    for arm in ('PRE','X1','X2','X3'):
        levers += [('IDLE-'+arm,ns,'IDLE','1s',1,1,-1) for ns in ('normal','db0')]
    with concurrent.futures.ThreadPoolExecutor(8) as pool:
        rows=list(pool.map(s.trace,ordinary+levers))
    builds={arm+'-'+ns:json.loads((s.OUT/(arm+'-'+ns+'-build.json')).read_text())
            for arm,ns in sorted({(r['arm'],r['namespace']) for r in rows})}
    comparisons=[]
    for arm in ('POST','PAD-A'):
        pairs=[]
        for row in rows:
            if row['arm']!=arm:continue
            keys=('namespace','command','mode','batch','atomic','threshold')
            pre=next(r for r in rows if r['arm']=='PRE' and all(row[k]==r[k] for k in keys))
            pairs.append({k:row[k] for k in keys}|dict(pre=pre['total'],post=row['total'],delta=row['total']-pre['total']))
        comparisons.append(dict(arm=arm,cases=pairs,case_count=len(pairs),
                                passed=len(pairs)==48 and all(r['delta']<=0 for r in pairs)))
    s.save(ROOT/'docs/exec1s/command-counts.json',dict(
        scope='named linked production bodies, libraries and fixture glue excluded; exact data checks required',
        ordinary_cases=len(ordinary),comparisons=comparisons,builds=builds,
        results=[r for r in rows if r['arm'] in ('PRE','POST','PAD-A')]))
    s.save(ROOT/'docs/exec1s/lever-counts.json',dict(
        scope='X1 idle/ring and owner; X2 eight same-shard EXEC owner batch; X3 idle rotation; X4 parsed EXEC prefix WB; X5 IO preparation/dispatch',
        builds=builds,results=[r for r in rows if r['arm'] not in ('PRE','POST','PAD-A')]))
    for c in comparisons:print(c['arm'],'PASS' if c['passed'] else 'FAIL',c['case_count'],flush=True)
    assert all(c['passed'] for c in comparisons), 'ordinary instruction regression'

if __name__=='__main__':main()
