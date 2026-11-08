#!/usr/bin/env python3
"""scriptfix4 finite instruction census: linked production objects, no server, no rates.

ordinary: GET/SET/INCR/MGET/MSET, batches 1 and 32, 1s/2s, atomic 0/1 and both compiled
          namespaces, in the 'complete' domain (every in-image tomo function).
scripts:  one warm EVAL/EVALSHA/FCALL activation (single and cross shard; an INCR body and a
          no-writes GET body), CLIENT TRACKING off and on (TRACK-), in the 'lua' domain, which
          also counts the vendored VM and the instruction hook.
The census engine, tracer and exact-reply fixture pattern are wave12/scriptfix3/clientcompat's
(tools/wave12_counts.py, tools/scriptfix3_trace.cc); tests/scriptfix4_scope.cc is the fixture.
"""
import argparse
import concurrent.futures
import itertools
import os
from pathlib import Path
import subprocess

import wave12_counts as census

ROOT = Path(__file__).resolve().parents[1]
ARMS = {'PRE': (ROOT / 'build/scriptfix4/pre-source', ROOT / 'build/scriptfix4/pre'),
        'POST': (ROOT, ROOT / 'build')}


def main():
    assert os.sched_getaffinity(0) <= set(range(87, 100)), 'run under taskset -c 87-99'
    os.environ['LC_ALL'] = 'C'
    parser = argparse.ArgumentParser()
    parser.add_argument('arm', choices=sorted(ARMS))
    parser.add_argument('--kind', choices=('ordinary', 'scripts'), required=True)
    parser.add_argument('--only', default='')
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--workers', type=int, default=6)
    args = parser.parse_args()
    census.BUILD = ROOT / 'build/scriptfix4/counts'
    census.DOC = ROOT / 'docs/scriptfix4/instructions'
    census.BUILD.mkdir(parents=True, exist_ok=True)
    tracer = census.BUILD / 'trace'
    if not tracer.exists():
        temporary = census.BUILD / ('trace-' + str(os.getpid()))
        subprocess.run(['g++', '-std=c++20', '-O2', '-g', str(ROOT / 'tools/scriptfix3_trace.cc'),
                        '-o', str(temporary)], check=True)
        temporary.replace(tracer)
    source, objects = ARMS[args.arm]
    if args.kind == 'ordinary':
        commands, domain, batches = ['GET', 'SET', 'INCR', 'MGET', 'MSET'], 'complete', (1, 32)
    else:
        commands = [track + verb + '-' + place + header for track in ('', 'TRACK-')
                    for verb in ('EVAL', 'EVALSHA', 'FCALL') for place in ('single', 'cross')
                    for header in ('', '-header')]
        domain, batches = 'lua', (1,)
    if args.only:
        commands = args.only.split(',')
    rows = []
    for namespace in ('normal', 'db0'):
        binary = (census.BUILD / 'scopes' / (args.arm + '-' + namespace) / 'probe' if args.no_build
                  else census.build(args.arm, source, objects, namespace, 'tests/scriptfix4_scope.cc'))
        prepared = census.prepare(binary, objects, namespace, domain)
        cases = list(itertools.product(commands, ('1s', '2s'), batches, (0, 1)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            rows += list(pool.map(lambda case: census.trace(prepared, args.arm, namespace, domain, *case),
                                  cases))
    census.save(census.DOC / args.arm / (args.kind + '-counts.json'),
                dict(server_sha256=census.sha(objects / 'tomokv'), tracer_sha256=census.sha(tracer),
                     domain=domain, rows=rows))


if __name__ == '__main__':
    main()
