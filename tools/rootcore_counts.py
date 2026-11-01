#!/usr/bin/env python3
"""Rootcore's bounded serverless command census; no listener or rate measurement."""
import argparse
import concurrent.futures
import os
from pathlib import Path
import subprocess
import wave12_counts as census

p=argparse.ArgumentParser()
p.add_argument('arm')
p.add_argument('--source', type=Path, required=True)
p.add_argument('--objects', type=Path, required=True)
a=p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16,32))
os.environ['LC_ALL']='C'
census.BUILD=census.ROOT/'build/rootcore/counts'
census.DOC=census.ROOT/'docs/rootcore/instructions'
census.BUILD.mkdir(parents=True,exist_ok=True)
subprocess.run(['g++','-std=c++20','-O2','-g','tools/scriptfix3_trace.cc',
                '-o',str(census.BUILD/'trace')],check=True)
rows=[]
for ns in ('normal','db0'):
    binary=census.build(a.arm,a.source.resolve(),a.objects.resolve(),ns,'tests/wave12_scope.cc')
    prepared=census.prepare(binary,a.objects.resolve(),ns,'complete')
    cases=[(cmd,mode,batch,atomic) for cmd in ('GET','SET','INCR','MGET','MSET')
           for mode in ('1s','2s') for batch in (1,32)
           for atomic in ((0,1) if cmd=='MSET' else (1,))]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        rows+=list(pool.map(lambda x:census.trace(prepared,a.arm,ns,'complete',*x),cases))
census.save(census.DOC/(a.arm+'.json'),rows)
