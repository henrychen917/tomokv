#!/usr/bin/env python3
"""Finite production instruction census. No server, timing, or rates."""
import argparse
import concurrent.futures
import itertools
import os
from pathlib import Path
import subprocess

import wave12_counts as census


def main():
    assert os.sched_getaffinity(0) <= set(range(64, 80))
    os.environ['LC_ALL'] = 'C'
    parser = argparse.ArgumentParser()
    parser.add_argument('arm', choices=('PRE', 'POST'))
    parser.add_argument('--only', default='')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--session', action='store_true')
    parser.add_argument('--all-executable', action='store_true',
                        help='also count out-of-line STL code; keep fixture instructions excluded')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    census.BUILD = root / 'build/clientcompat/counts'
    census.DOC = root / 'docs/clientcompat/instructions'
    census.BUILD.mkdir(parents=True, exist_ok=True)
    source = root / 'build/clientcompat/PRE' if args.arm == 'PRE' else root
    objects = source if args.arm == 'PRE' else root / 'build'
    tracer = census.BUILD / 'trace'
    if not tracer.exists():
        subprocess.run(['g++', '-std=c++20', '-O2', '-g',
                        'tools/scriptfix3_trace.cc', '-o', str(tracer)], check=True)
    commands = [prefix + verb for prefix in ('', 'TRACK-')
                for verb in ('GET', 'SET', 'INCR', 'MGET', 'MSET')]
    label = args.arm + ('-session' if args.session else '')
    if args.session:
        commands = [prefix + verb for prefix in ('', 'TRACK-') for verb in
                    ('EXEC-single', 'EXEC-cross', 'EXEC-reads-single', 'EXEC-reads-cross')]
    if args.only:
        commands = args.only.split(',')
    rows = []
    build_label = label
    if args.all_executable:
        label += '-elf'
    for namespace in ('normal', 'db0'):
        binary = (census.BUILD / 'scopes' / (build_label + '-' + namespace) / 'probe'
                  if args.no_build else census.build(build_label, source, objects, namespace,
                      'tests/clientcompat_session_scope.cc' if args.session
                      else 'tests/clientcompat_scope.cc'))
        prepared = census.prepare(binary, objects, namespace, 'complete')
        if args.all_executable:
            ranges, argv, digest = prepared
            for row in ranges:
                row[4] = not ('CoreConcurrencyTest::' in row[3] or row[2] in
                              ('main', '_Z11scope_beginv', '_Z9scope_endv'))
            whole = binary.parent/'elf.ranges'
            whole.write_text(''.join(f'{r[0]:x} {r[1]:x} {int(r[4])}\n' for r in ranges))
            argv[2] = str(whole)
        cases = list(itertools.product(commands, ('1s', '2s'), (1, 4) if args.session else (1, 32), (0, 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            rows += list(pool.map(lambda case: census.trace(
                prepared, label, namespace, 'complete', *case), cases))
    census.save(census.DOC / label / 'counts.json', dict(
        server_sha256=census.sha(objects / 'tomokv'), rows=rows))


if __name__ == '__main__':
    main()
