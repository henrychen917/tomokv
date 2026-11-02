#!/usr/bin/env python3
"""Finite production instruction scopes, no servers, rates or PMU sampling."""
import argparse
import concurrent.futures
import itertools
import os
from pathlib import Path
import subprocess
import wave12_counts as census

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('arm', choices=['PRE', 'POST', 'PAD-A'])
p.add_argument('--source', type=Path, required=True)
p.add_argument('--objects', type=Path, required=True)
p.add_argument('--contended', action='store_true')
a = p.parse_args()
assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
os.environ['LC_ALL'] = 'C'
census.BUILD = census.ROOT / ('build/atomfix6/contended' if a.contended else 'build/atomfix6/counts')
census.DOC = census.ROOT / ('docs/atomfix6/contended' if a.contended else 'docs/atomfix6/counts')
census.BUILD.mkdir(parents=True, exist_ok=True)
tracer = census.BUILD / 'trace'
if not tracer.exists():
    subprocess.run(['g++', '-std=c++20', '-O2', '-g', 'tools/scriptfix3_trace.cc',
                    '-o', str(tracer)], check=True)
rows = []
for ns in ('normal', 'db0'):
    binary = census.build(a.arm, a.source.resolve(), a.objects.resolve(), ns,
                          'tests/atomfix6_park_scope.cc' if a.contended else 'tests/txnorder_command_scope.cc')
    prepared = census.prepare(binary, a.objects.resolve(), ns, 'complete')
    ranges, argv, digest = prepared
    # Include outlined STL and allocation wrappers; exclude only fixture glue.
    for row in ranges:
        row[4] = not (('CoreConcurrencyTest::' in row[3] and '::poll<' not in row[3]) or row[2] in
                      ('main', '_Z11scope_beginv', '_Z9scope_endv'))
    whole = binary.parent / 'all-executable.ranges'
    whole.write_text(''.join(f'{r[0]:x} {r[1]:x} {int(r[4])}\n' for r in ranges))
    argv[2] = str(whole)
    cases = itertools.product(('MGET', 'MSET') if a.contended else ('GET', 'SET', 'INCR', 'MGET', 'MSET'), ('1s', '2s'), (1, 32), (1,) if a.contended else (0, 1))
    with concurrent.futures.ThreadPoolExecutor(6) as pool:
        rows += list(pool.map(lambda case: census.trace(prepared, a.arm, ns, 'complete', *case), cases))
census.save(census.DOC / a.arm / 'counts.json', rows)
