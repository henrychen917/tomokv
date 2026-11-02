#!/usr/bin/env python3
"""Finite command-scope instruction counts; no listener, PMU, load or rate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import wave13_counts as census

p = argparse.ArgumentParser()
p.add_argument('arm'); p.add_argument('--source', type=Path, required=True)
p.add_argument('--objects', type=Path, required=True)
p.add_argument('--no-build', action='store_true')
a = p.parse_args()
assert os.sched_getaffinity(0) <= set(range(16, 24))
os.environ['LC_ALL'] = 'C'
census.BUILD = census.ROOT/'build/storefix5/counts'
census.DOC = census.ROOT/'docs/storefix5/counts'
census.BUILD.mkdir(parents=True, exist_ok=True)
tracer = census.BUILD/'trace'
if not tracer.exists():
    subprocess.run(['g++', '-std=c++20', '-O2', '-g', 'tools/scriptfix3_trace.cc',
                    '-o', str(tracer)], check=True)
source, objects = a.source.resolve(), a.objects.resolve()
rows = []
for namespace in ('normal', 'db0'):
    binary = (census.BUILD/'scopes'/(a.arm+'-'+namespace)/'probe' if a.no_build else
              census.build(a.arm, source, objects, namespace, 'tests/blockfix4_scope.cc'))
    prepared = census.prepare(binary, objects, namespace, 'complete')
    cases = [(verb, mode, batch, atomic) for verb in ('GET','SET','INCR','MGET','MSET')
             for mode in ('1s','2s') for batch in (1,32) for atomic in (0,1)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows += list(pool.map(lambda case: census.trace(prepared, a.arm, namespace,
                                                        'complete', *case), cases))
census.save(census.DOC/a.arm/'counts.json', dict(rows=rows,
    server_sha256=census.sha(objects/'tomokv'), tracer_sha256=census.sha(tracer)))
