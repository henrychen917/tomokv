#!/usr/bin/env python3
"""Finite serverless instruction counts; production code, no workload rate."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import wave13_counts as census
from cmdfix2_compact_units import loaded

ROOT = Path(__file__).resolve().parents[1]
census.BUILD = ROOT / 'build/cmdfix2/counts'
census.DOC = ROOT / 'docs/cmdfix2/instructions'


def main():
    assert os.sched_getaffinity(0) <= set(range(100, 112))
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser()
    p.add_argument('arm', choices=('PRE', 'POST'))
    p.add_argument('--only', default='GET,SET,INCR,MGET,MSET,PUBLISH,PUBLISH-ACL,GEOSEARCH,EXEC-single')
    p.add_argument('--no-build', action='store_true')
    a = p.parse_args()
    source = ROOT / 'build/cmdfix2/pre-source' if a.arm == 'PRE' else ROOT
    objects = ROOT / 'build/cmdfix2/pre-objects' if a.arm == 'PRE' else ROOT / 'build'
    census.BUILD.mkdir(parents=True, exist_ok=True)
    tracer = census.BUILD / 'trace'
    if not tracer.exists():
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', 'tools/scriptfix3_trace.cc', '-o', str(tracer)], check=True)
    rows = []
    for ns in ('normal', 'db0'):
        binary = (census.BUILD / 'scopes' / (a.arm + '-' + ns) / 'probe' if a.no_build else
                  census.build(a.arm, source, objects, ns, 'tests/cmdfix2_scope.cc'))
        if not a.no_build:
            before = loaded(binary)
            subprocess.run(['objcopy', '--compress-debug-sections=zlib', str(binary)], check=True)
            assert loaded(binary) == before
            recipe = census.DOC / a.arm / (ns + '-build.json')
            data = json.loads(recipe.read_text())
            data.update(probe_sha256=census.sha(binary), debug_compressed=True, loaded_sections_identical=True)
            census.save(recipe, data)
        prepared = census.prepare(binary, objects, ns, 'lua')  # includes outlined STL, excludes fixture/shared libs
        cases = [(c, mode, batch, atomic) for c in a.only.split(',')
                 for mode in ('1s', '2s') for batch in (1, 32) for atomic in (0, 1)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows += list(pool.map(lambda case: census.trace(prepared, a.arm, ns, 'lua', *case), cases))
    census.save(census.DOC / a.arm / 'counts.json', dict(server_sha256=census.sha(objects / 'tomokv'),
                fixture_sha256=census.sha(ROOT / 'tests/cmdfix2_scope.cc'), rows=rows))


if __name__ == '__main__':
    main()
