#!/usr/bin/env python3
"""iowake zero-cost census: finite production-object command scopes, no server or rates.

Links each arm's own production objects to the existing serverless owner/scatter fixture
(tests/wave11_scope.cc) and ptrace-counts executed server instructions for GET/SET/INCR/MGET/MSET
x 1s/2s x batch 1/32 x atomic 0/1 x normal/db0 namespaces (80 cases per arm). Same tracer and
accounting as tools/netfix2_counts.py; only the arm paths differ.

  taskset -c 64-95 python3 tools/iowake_counts.py PRE    # build/iowake/pre-source + build/iowake/pre
  taskset -c 64-95 python3 tools/iowake_counts.py POST   # this tree + build/
"""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys

import wave11_counts as scope

ROOT = Path(__file__).resolve().parents[1]
scope.BUILD = ROOT / 'build/iowake/counts'
scope.DOC = ROOT / 'docs/iowake/counts'


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 96)), 'iowake lane CPUs are 64-95'
    os.environ['LC_ALL'] = 'C'
    arm = sys.argv[1]
    source, objects = ((ROOT / 'build/iowake/pre-source', ROOT / 'build/iowake/pre')
                       if arm == 'PRE' else (ROOT, ROOT / 'build'))
    scope.BUILD.mkdir(parents=True, exist_ok=True)
    tracer = scope.BUILD / 'trace'
    if not tracer.exists():
        subprocess.run(['g++', '-std=c++20', '-O2', 'tools/scriptfix3_trace.cc', '-o', str(tracer)],
                       check=True, cwd=ROOT)
    rows = []
    for ns in ('normal', 'db0'):
        binary = scope.build(arm, source, objects, ns, 'tests/wave11_scope.cc')
        prepared = scope.prepare(binary, objects, ns, 'complete')
        cases = [(cmd, mode, batch, atomic) for cmd in ('GET', 'SET', 'INCR', 'MGET', 'MSET')
                 for mode in ('1s', '2s') for batch in (1, 32) for atomic in (0, 1)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows += list(pool.map(lambda c: scope.trace(prepared, arm, ns, 'complete', *c), cases))
    scope.save(scope.DOC / arm / 'results.json', rows)
    if arm == 'POST':
        pre = json.loads((scope.DOC / 'PRE/results.json').read_text())
        key = lambda r: tuple(r[k] for k in ('namespace', 'command', 'mode', 'batch', 'atomic'))
        old = {key(r): r for r in pre}
        comparison = [dict(namespace=r['namespace'], command=r['command'], mode=r['mode'],
                           batch=r['batch'], atomic=r['atomic'], pre=old[key(r)]['total'],
                           post=r['total'], delta=r['total'] - old[key(r)]['total'],
                           functions_equal=r['functions'] == old[key(r)]['functions'])
                      for r in rows]
        scope.save(scope.DOC / 'comparison.json', comparison)
        print('Nonzero deltas:', [r for r in comparison if r['delta']], flush=True)
        assert len(comparison) == 80 and not any(r['delta'] for r in comparison), comparison


if __name__ == '__main__':
    main()
