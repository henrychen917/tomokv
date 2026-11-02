#!/usr/bin/env python3
"""Serverless production command census. No server, rate, or load generator."""
import concurrent.futures
import os
from pathlib import Path
import subprocess
import sys

import wave13_counts as count

assert os.sched_getaffinity(0) <= set(range(32, 48)), 'cfgfix2 CPU boundary'
os.environ['LC_ALL'] = 'C'
root = Path(__file__).resolve().parents[1]
count.BUILD = root / 'build/cfgfix2/counts'
count.DOC = root / 'docs/cfgfix2/instructions'
count.BUILD.mkdir(parents=True, exist_ok=True)
label = sys.argv[1]
source = root / 'build/cfgfix2/pre-source' if label == 'PRE' else root
objects = source / 'build'
subprocess.run(['g++', '-std=c++20', '-O2', '-g', 'tools/scriptfix3_trace.cc',
                '-o', str(count.BUILD / 'trace')], check=True)
rows = []
for ns in ('normal', 'db0'):
    binary = count.build(label, source, objects, ns, 'tests/wave11_scope.cc')
    prepared = count.prepare(binary, objects, ns, 'complete')
    cases = [(command, mode, batch, atomic)
             for command in ('GET', 'SET', 'INCR', 'MGET', 'MSET')
             for mode in ('1s', '2s') for batch in (1, 32)
             for atomic in ((0, 1) if command == 'MSET' else (1,))]
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows += list(pool.map(lambda case: count.trace(prepared, label, ns, 'complete', *case), cases))
count.save(count.DOC / label / 'counts.json', dict(server_sha256=count.sha(objects / 'tomokv'),
           tracer_sha256=count.sha(count.BUILD / 'trace'), rows=rows))
