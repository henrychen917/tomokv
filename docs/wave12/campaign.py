#!/usr/bin/env python3
"""Run the declared correctness matrix through gate.sh's whole-job interface."""
import argparse, hashlib, json, os, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave12'
M=json.loads((DOC/'correctness-matrix.json').read_text())
os.sched_setaffinity(0,set(range(64,96)))
p=argparse.ArgumentParser()
p.add_argument('phase',choices=('main','secondary','quiet','differ','bounds0'))
p.add_argument('--asan-binary',type=Path)
p.add_argument('--prefix',default='landing')
a=p.parse_args()
runs=[]
quiet={'atomic_batteries','perfio_stream'}
if a.phase=='main':
    jobs=list(dict.fromkeys(sum((M[k] for k in ('once','new_lanes_once','each_engine','each_mode','each_mode_engine')),[])))
    runs=[('main-2s-uring',[j for j in jobs if j not in quiet],False,'uring',{})]
elif a.phase=='secondary':
    for fused,engine in ((False,'epoll'),(True,'uring'),(True,'epoll')):
        jobs=M['each_mode_engine']+([] if fused else M['each_engine'])
        if fused and engine=='uring':jobs+=M['each_mode']
        runs.append((f"secondary-{'1s' if fused else '2s'}-{engine}",
                     [j for j in jobs if j not in quiet],fused,engine,{}))
elif a.phase=='quiet':
    # GATE_PROOF_NO_RATES also suppresses stream's three release memory bounds.
    # These four feature jobs contain no throughput/load-generator job; restore
    # their normal release assertions in both engines before the quiet checks.
    runs=[('footprints-'+engine,M['release_footprints_each_engine'],False,engine,{})
          for engine in ('uring','epoll')]
    for fused in (False,True):
        for engine in ('uring','epoll'):
            jobs=['atomic_batteries']
            if not fused and engine=='uring':jobs+=['perfio_stream','atomic_floor']
            runs.append((f"quiet-{'1s' if fused else '2s'}-{engine}",jobs,fused,engine,{}))
elif a.phase=='differ':
    runs=[('differ-'+engine,M['differ_each_engine'],False,engine,{}) for engine in ('uring','epoll')]
else:
    runs=[(f"bounds0-{'1s' if fused else '2s'}-{engine}",['script_bounds'],fused,engine,{'GATE_TXN_ATOMIC':'0'})
          for fused in (False,True) for engine in ('uring','epoll')]
failed=False
for name,jobs,fused,engine,extra in runs:
    name=a.prefix+'-'+name
    receipt=DOC/'jobs'/(name+'.json')
    if receipt.exists():
        result=json.loads(receipt.read_text())
        assert result['binary_sha256']==hashlib.sha256((ROOT/'build/wave12/tomokv-POST').read_bytes()).hexdigest(), 'new arm requires a new run prefix'
        print('retained',name,result['exit'],flush=True)
        failed |= result['exit']!=0
        continue
    argv=[sys.executable,str(DOC/'run_jobs.py'),name,*dict.fromkeys(jobs),
          '--binary','build/tomokv','--engine',engine,'--port','20020']
    if fused:argv+=['--fused']
    footprints=name.startswith(a.prefix+'-footprints-')
    if footprints:argv+=['--release-footprints']
    if a.phase in ('quiet','bounds0') and not footprints:argv+=['--single-slot']
    if a.asan_binary:argv+=['--asan-binary',str(a.asan_binary.resolve())]
    print('running',name,len(jobs),'jobs',flush=True)
    result=subprocess.run(argv,cwd=ROOT,env=dict(os.environ,**extra))
    failed |= result.returncode!=0
raise SystemExit(int(failed))
