#!/usr/bin/env python3
"""Summarize finite instruction scopes and bind entered bodies to each arm."""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import wave14

KINDS = ('ordinary', 'scripts', 'session', 'other', 'parser')


def key(row):
    return tuple(row[k] for k in ('namespace', 'command', 'mode', 'batch', 'atomic', 'local'))


def compare():
    rows = []
    arms = {}
    for kind in KINDS:
        sources = {arm: json.loads((wave14.DOC/'instructions'/f'{arm}-{kind}'/'counts.json').read_text())
                   for arm in ('pre', 'post')}
        arms[kind] = {arm: d['server_sha256'] for arm, d in sources.items()}
        pre = {key(r): r for r in sources['pre']['rows']}
        post = {key(r): r for r in sources['post']['rows']}
        assert pre.keys() == post.keys()
        for k, a in pre.items():
            b = post[k]
            functions = {name: b['functions'].get(name, 0)-a['functions'].get(name, 0)
                         for name in a['functions'].keys() | b['functions'].keys()}
            rows.append(dict(kind=kind, cell=k, pre=a['total'], post=b['total'],
                added=b['total']-a['total'],
                function_deltas={n: v for n, v in sorted(functions.items()) if v}))
    assert len(rows) == 216
    result = dict(arms=arms, cells=len(rows),
        get_set_incr_added=[r for r in rows if r['cell'][1] in ('GET', 'SET', 'INCR') and r['added']>0],
        rows=rows)
    wave14.save(wave14.DOC/'instruction-comparison.json', result)
    lines = ['# Serverless instruction census', '',
        'Finite command scopes; executable instructions include outlined STL and Lua. Shared libraries, fixture glue and synthetic clock calls are excluded. No rate or timing claim.', '',
        '| Kind | Namespace | Command | Mode | Batch | Atomic | Read-local | PRE | POST | Added |',
        '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append('| '+' | '.join(map(str, (r['kind'], *r['cell'], r['pre'], r['post'], r['added'])))+' |')
    (wave14.DOC/'instruction-comparison.md').write_text('\n'.join(lines)+'\n')
    print('cells', len(rows), 'GET/SET/INCR positive deltas', len(result['get_set_incr_added']))


def binding(job):
    arm, kind, ns = job
    audit = wave14.references()
    folder = wave14.DOC/'instructions'/f'{arm}-{kind}'
    build = json.loads((folder/(ns+'-build.json')).read_text())
    probe = Path(build['link'][build['link'].index('-o')+1])
    server = wave14.PRE/'build/tomokv' if arm == 'pre' else wave14.ROOT/'build/tomokv'
    assert wave14.sha(probe) == build['probe_sha256']
    assert wave14.sha(server) == build['server_sha256']
    production, fixture = audit.inventory(server), audit.inventory(probe)
    names = set()
    for row in json.loads((folder/'counts.json').read_text())['rows']:
        if row['namespace'] == ns:
            names.update(audit.audit.canonical(n) for n in row['functions'])
    rows = []
    for name in sorted(names):
        before = production['groups'].get(name, [])
        after = fixture['groups'].get(name, [])
        # Group multiplicity can increase when a fixture emits its own template
        # instance. Preserve every digest; do not normalize away a new body.
        matches = bool(after) and {r['digest'] for r in after} <= {r['digest'] for r in before}
        rows.append(dict(name=name, equal=matches,
            server_digests=[r['digest'] for r in before], probe_digests=[r['digest'] for r in after]))
    result = dict(arm=arm, kind=kind, namespace=ns, server_sha256=production['sha256'],
        probe_sha256=fixture['sha256'], entered_groups=len(rows),
        matched=sum(r['equal'] for r in rows), unmatched=[r for r in rows if not r['equal']])
    wave14.save(wave14.DOC/'scope-binding'/f'{arm}-{kind}-{ns}.json', result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('phase', choices=('compare','bind'))
    p.add_argument('--arm', choices=('pre','post','both'), default='both')
    a=p.parse_args()
    if a.phase == 'compare': compare()
    else:
        arms=('pre','post') if a.arm=='both' else (a.arm,)
        with ProcessPoolExecutor(max_workers=6) as pool:
            rows=list(pool.map(binding, [(arm,kind,ns) for arm in arms for kind in KINDS for ns in ('normal','db0')]))
        wave14.save(wave14.DOC/f'scope-binding-{a.arm}.json', rows)
        print([(r['arm'],r['kind'],r['namespace'],len(r['unmatched'])) for r in rows])


if __name__ == '__main__': main()
