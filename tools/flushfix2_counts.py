#!/usr/bin/env python3
"""Finite serverless command scopes, using the established production fixture.

Only the owned fixture child is stepped. No server, listener, debugger attach,
core dump, throughput or timing measurement. Counts include executed NOPs in
named TomoKV bodies and exclude library callees and fixture glue.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import subprocess

import crlffix_scope as scope
import crlffix_fast_scope as fast

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/flushfix2/counts'
OUT = ROOT / 'docs/flushfix2/counts'
scope.BUILD = BUILD
scope.OUT = OUT
scope.ARMS = {'pre': (ROOT / 'build/flushfix2/pre-source', ROOT / 'build/flushfix2/pre'),
              'post': (ROOT, ROOT / 'build')}


def run(case, prepared):
    arm, ns, command, mode, batch, atomic, threshold = case
    binary, plan, ranges = prepared[arm, ns]
    label = '-'.join(map(str, case))
    raw_file = BUILD / (label + '.json')
    argv = [str(BUILD / 'step'), str(plan), str(raw_file), str(binary),
            command, mode, str(batch), str(atomic), str(threshold)]
    with (BUILD / (label + '.log')).open('w') as log:
        subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
    raw = json.loads(raw_file.read_text())
    functions = {}
    for n, r in zip(raw.pop('counts')[1:], ranges):
        if n:
            functions[r[3]] = functions.get(r[3], 0) + n
    assert functions
    row = dict(zip(('arm', 'namespace', 'command', 'mode', 'batch', 'atomic', 'threshold'), case))
    row.update(raw, total=sum(functions.values()), functions=functions,
               probe_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (OUT / (label + '.json')).write_text(json.dumps(row, indent=2) + '\n')
    raw_file.unlink()
    print(label, row['total'], flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arms', default='pre,post')
    p.add_argument('--build-only', action='store_true')
    p.add_argument('--trace-only', action='store_true')
    p.add_argument('--commands', default='GET,SET,INCR,MGET,MSET')
    p.add_argument('--jobs', type=int, default=4)
    args = p.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    arms = args.arms.split(',')
    if not args.trace_only:
        subprocess.run(['gcc', '-O2', str(ROOT / 'tools/crlffix_step.c'), '-o', str(BUILD / 'step')], check=True)
        for arm in arms:
            for ns in ('normal', 'db0'):
                scope.build(arm, ns)
    if args.build_only:
        return
    prepared = {(arm, ns): fast.prepare(arm, ns) for arm in arms for ns in ('normal', 'db0')}
    cases = [(arm, ns, command, mode, batch, atomic, -1) for arm in arms
             for ns in ('normal', 'db0') for command in args.commands.split(',')
             for mode in ('1s', '2s') for batch in (1, 32) for atomic in (0, 1)]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        rows = list(pool.map(lambda case: run(case, prepared), cases))
    (OUT / ('results-' + args.arms + '.json')).write_text(json.dumps(rows, indent=2) + '\n')
    if arms == ['pre', 'post']:
        pairs = []
        for r in rows:
            if r['arm'] != 'post':
                continue
            keys = ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold')
            old = next(o for o in rows if o['arm'] == 'pre' and all(o[k] == r[k] for k in keys))
            pairs.append({k: r[k] for k in keys} | dict(pre=old['total'], post=r['total'],
                         delta=r['total'] - old['total'], functions_equal=r['functions'] == old['functions']))
        (OUT / 'comparison.json').write_text(json.dumps(pairs, indent=2) + '\n')


if __name__ == '__main__':
    main()
