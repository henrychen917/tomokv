#!/usr/bin/env python3
"""Build production-linked RL5 witnesses and finite instruction censuses (no rates)."""
import argparse
import bisect
import csv
from concurrent.futures import ThreadPoolExecutor
import gzip
import json
import os
from pathlib import Path
import subprocess

import wave13_counts as census

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/rlfix5/counts'
DOC = ROOT / 'docs/rlfix5/counts'
census.BUILD, census.DOC = BUILD, DOC


def trace(prepared, arm, ns, case):
    ranges, argv, digest = prepared
    out = DOC / arm / ('-'.join(map(str, (ns, *case))) + '.json')
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and json.loads(out.read_text())['probe_sha256'] == digest:
        return json.loads(out.read_text())
    p = subprocess.run(argv + list(map(str, case)), text=True, capture_output=True, timeout=900)
    if p.returncode:
        out.with_suffix('.failed.log').write_text(p.stdout[-2000:] + p.stderr)
        raise RuntimeError(str(out) + ': ' + p.stderr[-1000:])
    record = json.loads(next(line[6:] for line in p.stdout.splitlines() if line.startswith('TRACE=')))
    starts = [r[0] for r in ranges]
    functions = {}
    for pc, n in record['sites'].items():
        i = bisect.bisect_right(starts, int(pc, 16)) - 1
        assert i >= 0 and int(pc, 16) < ranges[i][1]
        name = ranges[i][3]
        functions[name] = functions.get(name, 0) + n
    row = dict(arm=arm, namespace=ns, command=case[0], mode=case[1], batch=case[2],
               local=case[3], tracking=case[4], probe_sha256=digest,
               tracer_sha256=census.sha(BUILD / 'trace'), total=sum(functions.values()),
               functions=functions, clock_calls=record['clock_calls'], excluded_calls=record['excluded_calls'])
    census.save(out, row)
    with gzip.GzipFile(filename=str(out) + '.sites.gz', mode='wb', mtime=0) as f:
        f.write(json.dumps(record).encode())
    out.with_suffix('.log').write_text(' '.join(argv + list(map(str, case))) + '\n' + p.stderr +
        '\n'.join(line for line in p.stdout.splitlines() if not line.startswith('TRACE=')))
    print(arm, ns, *case, row['total'], flush=True)
    return row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=('build', 'count', 'scatter-build', 'scatter-count', 'compare'))
    p.add_argument('--arm', choices=('pre', 'post', 'pad-a'), required=True)
    p.add_argument('--only', default='')
    a = p.parse_args()
    assert len(os.sched_getaffinity(0)) >= 8, 'fixture requires eight inherited CPUs'
    os.environ['LC_ALL'] = 'C'
    if a.action == 'compare':
        keys = ('namespace', 'command', 'mode', 'batch', 'local', 'tracking')
        before = {tuple(r[k] for k in keys): r for r in json.loads((DOC / 'pre/counts.json').read_text())['rows']}
        rows = []
        for r in json.loads((DOC / a.arm / 'counts.json').read_text())['rows']:
            old = before[tuple(r[k] for k in keys)]
            protected = (r['local'] == 0 and r['command'] in ('GET', 'SET', 'INCR', 'MGET', 'MSET')) or (
                r['local'] == 1 and r['tracking'] == 0 and r['command'] in ('GET', 'MGET'))
            rows.append(dict(**{k: r[k] for k in keys}, pre=old['total'], post=r['total'],
                             delta=r['total'] - old['total'], protected=protected))
        with (DOC.parent / 'count-deltas.csv').open('w') as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator='\n')
            writer.writeheader(); writer.writerows(rows)
        protected = [r for r in rows if r['protected']]
        result = dict(cases=len(rows), protected_cases=len(protected),
                      positive_protected=[r for r in protected if r['delta'] > 0], rows=rows)
        census.save(DOC.parent / 'count-deltas.json', result)
        print('protected', len(protected), 'positive', result['positive_protected'], flush=True)
        raise SystemExit(bool(result['positive_protected']))
    source = ROOT / 'build/rlfix5/pre/source' if a.arm in ('pre', 'pad-a') else ROOT
    objects = ROOT / 'build/rlfix5/pre/objects' if a.arm in ('pre', 'pad-a') else ROOT / 'build'
    scatter = a.action.startswith('scatter-')
    label = a.arm + ('-scatter' if scatter else '')
    rows = []
    for ns in ('normal', 'db0'):
        if a.action.endswith('build'):
            census.build(label, source, objects, ns,
                         'tests/blockfix4_scope.cc' if scatter else 'tests/rlfix5_scope.cc')
            if a.arm == 'pad-a':
                # Use the same PRE objects, cold alignment and unexecuted pad as
                # the frozen behaviour twin; never pair it with a POST witness.
                pad = json.loads((DOC.parent / 'pad-a.json').read_text())
                meta_path = DOC / label / (ns + '-build.json')
                meta = json.loads(meta_path.read_text())
                replacements = {str(objects / name): str(ROOT / 'build/rlfix5/pad-a/objects' / name)
                                for name in pad['cold_alignment_compacted']}
                meta['link'] = [replacements.get(x, x) for x in meta['link']] + [pad['link'][-1]]
                subprocess.run(meta['link'], check=True)
                meta['probe_sha256'] = census.sha(BUILD / 'scopes' / (label + '-' + ns) / 'probe')
                meta['server_sha256'] = pad['sha256']
                meta['pad_kind'] = pad['kind']
                census.save(meta_path, meta)
            continue
        binary = BUILD / 'scopes' / (label + '-' + ns) / 'probe'
        if not (BUILD / 'trace').exists():
            subprocess.run(['g++', '-std=c++20', '-O2', '-g', str(ROOT / 'tools/scriptfix3_trace.cc'),
                            '-o', str(BUILD / 'trace')], check=True)
        prepared = census.prepare(binary, objects, ns, 'lua')
        if scatter:
            cases = [(command, mode, batch, atomic) for command in ('MGET', 'MSET')
                     for mode in ('1s', '2s') for batch in (1, 32) for atomic in (0, 1)]
            with ThreadPoolExecutor(max_workers=8) as pool:
                rows += list(pool.map(lambda c: census.trace(prepared, label, ns, 'lua', *c), cases))
            continue
        verbs = a.only.split(',') if a.only else ('GET', 'SET', 'INCR', 'MGET', 'MSET',
                                                 'STRLEN', 'EXISTS', 'GETRANGE', 'TYPE', 'TTL', 'OBJECT')
        cases = [(cmd, mode, batch, local, tracking) for cmd in verbs
                 for mode in ('1s', '2s') for batch in (1, 32)
                 for local, tracking in ((0, 0), (0, 1), (1, 0), (1, 1))]
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows += list(pool.map(lambda case: trace(prepared, a.arm, ns, case), cases))
    if rows:
        census.save(DOC / label / 'counts.json', dict(rows=rows))


if __name__ == '__main__':
    main()
