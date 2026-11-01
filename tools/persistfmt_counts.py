#!/usr/bin/env python3
"""PRE/POST bounded production instruction counts; no servers, PMU or rates.

Uses the gate's existing ptrace command-scope tracer and unmodified wave11
ordinary command fixture, plus a capture/load-loop fixture. External library
calls are excluded identically in both arms. Batch 1/32, atomic 0/1, both thread
modes and namespaces. Snapshot per-key cost is the (32-1)/31 marginal count.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import wave11_counts as counts

ROOT = Path(__file__).resolve().parents[1]
counts.BUILD = ROOT / 'build/persistfmt/counts'
counts.DOC = ROOT / 'docs/persistfmt/counts'


def main():
    assert set(os.sched_getaffinity(0)) <= set(range(96, 112))
    os.environ['LC_ALL'] = 'C'
    p = argparse.ArgumentParser()
    p.add_argument('arm')
    p.add_argument('--source', type=Path, default=ROOT)
    p.add_argument('--objects', type=Path, default=ROOT / 'build')
    p.add_argument('--server-binary', type=Path)
    p.add_argument('--only', default='GET,SET,INCR,MGET,MSET,SNAPSHOT-SAVE,SNAPSHOT-LOAD')
    p.add_argument('--no-build', action='store_true')
    args = p.parse_args()
    source, objects = args.source.resolve(), args.objects.resolve()
    server = (args.server_binary or objects / 'tomokv').resolve()
    counts.BUILD.mkdir(parents=True, exist_ok=True)
    if not (counts.BUILD / 'trace').exists():
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', 'tools/scriptfix3_trace.cc',
                        '-o', str(counts.BUILD / 'trace')], check=True)
    fixture = counts.BUILD / 'scope.cc'
    text = (ROOT / 'tests/wave11_scope.cc').read_text()
    text = text.replace('namespace tomo {\nstruct CoreConcurrencyTest',
        'extern "C" unsigned production_snapshot_progress(void*, unsigned, unsigned)\n'
        ' asm("_ZN" NSM "9FlatStore17snapshot_progressEjj");\n'
        'namespace tomo {\nstruct CoreConcurrencyTest', 1)
    marker = '  const unsigned io=Fused?7:0;'
    assert text.count(marker) == 1
    fixture.write_text(text.replace(marker, (ROOT / 'tests/persistfmt_snapshot_scope.inc').read_text() + marker))
    rows = []
    for namespace in ('normal', 'db0'):
        binary = counts.BUILD / 'scopes' / (args.arm + '-' + namespace) / 'probe'
        if not args.no_build:
            binary = counts.build(args.arm, source, objects, namespace, fixture)
            record = counts.DOC / args.arm / (namespace + '-build.json')
            build = json.loads(record.read_text())
            build['server_sha256'] = counts.sha(server)
            build['server_binary'] = str(server)
            counts.save(record, build)
        prepared = counts.prepare(binary, objects, namespace, 'complete')
        cases = [(c, m, b, a) for c in args.only.split(',') for m in ('1s', '2s')
                 for b in (1, 32) for a in ((0,) if c.startswith('SNAPSHOT-') else (0, 1))]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows += list(pool.map(lambda case: counts.trace(prepared, args.arm, namespace,
                                                            'complete', *case), cases))
    counts.save(counts.DOC / args.arm / 'counts.json', dict(rows=rows,
        server_sha256=counts.sha(server), tracer_sha256=counts.sha(counts.BUILD / 'trace')))


if __name__ == '__main__':
    main()
