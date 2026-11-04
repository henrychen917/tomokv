#!/usr/bin/env python3
"""Finite production-object instruction scopes; no server or rate measurement."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys

import wave11_counts as scope

ROOT = Path(__file__).resolve().parents[1]
scope.BUILD = ROOT / 'build/netfix2/counts'
scope.DOC = ROOT / 'docs/netfix2/counts'


def main():
    assert os.sched_getaffinity(0) <= set(range(8, 16))
    arm = sys.argv[1]
    source, objects = ((ROOT / 'build/netfix2/pre-source', ROOT / 'build/netfix2')
                       if arm == 'PRE' else (ROOT, ROOT / 'build'))
    scope.BUILD.mkdir(parents=True, exist_ok=True)
    tracer = scope.BUILD / 'trace'
    if not tracer.exists():
        subprocess.run(['g++', '-std=c++20', '-O2', 'tools/scriptfix3_trace.cc', '-o', str(tracer)], check=True)
    rows = []
    for ns in ('normal', 'db0'):
        binary = scope.build(arm, source, objects, ns, 'tests/wave11_scope.cc')
        prepared = scope.prepare(binary, objects, ns, 'complete')
        cases = [(cmd, mode, batch, atomic) for cmd in ('GET', 'SET', 'INCR', 'MGET', 'MSET')
                 for mode in ('1s', '2s') for batch in (1, 32) for atomic in (0, 1)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            rows += list(pool.map(lambda c: scope.trace(prepared, arm, ns, 'complete', *c), cases))
    scope.save(scope.DOC / arm / 'results.json', rows)
    if arm == 'POST':
        pre = json.loads((scope.DOC / 'PRE/results.json').read_text())
        key = lambda r: tuple(r[k] for k in ('namespace', 'command', 'mode', 'batch', 'atomic'))
        old = {key(r): r for r in pre}
        comparison = [dict(namespace=r['namespace'], command=r['command'], mode=r['mode'],
                           batch=r['batch'], atomic=r['atomic'], pre=old[key(r)]['total'],
                           post=r['total'], delta=r['total']-old[key(r)]['total']) for r in rows]
        scope.save(scope.DOC / 'comparison.json', comparison)
        print('Nonzero deltas:', [r for r in comparison if r['delta']], flush=True)
        assert len(comparison) == 80 and not any(r['delta'] for r in comparison), comparison


if __name__ == '__main__':
    main()
