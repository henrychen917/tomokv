#!/usr/bin/env python3
"""Summarize finite instruction scopes and bind entered bodies to each arm."""
import argparse
import bisect
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import re
import subprocess
import wave14

KINDS = ('ordinary', 'scripts', 'session', 'other', 'parser')


def rlfence(path):
    """Preserve assembly bytes and resolve its four relocated return jumps."""
    from lbstall_artifacts import Elf
    elf=Elf(path);section=elf.names.index('.rlfence');base=elf.sections[section][3]
    raw=bytearray(elf.section_data(section));targets=[]
    disassembly=subprocess.check_output(['objdump','-dw','-j','.rlfence',str(path)],text=True)
    for line in disassembly.splitlines():
        m=re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s+jmp\s+([0-9a-f]+)\s+<',line)
        if not m:continue
        encoded=bytes.fromhex(m[2]);assert len(encoded)==5 and encoded[0]==0xe9
        at,destination=int(m[1],16),int(m[3],16)
        candidates=[s for s in elf.symbols if s['info']&15==2 and s['size'] and
                    s['value']<=destination<s['value']+s['size']]
        assert candidates, 'unresolved assembly return target'
        target=min(candidates,key=lambda s:(s['size'],s['name']))
        targets.append((at-base,target['name'],destination-target['value']))
        raw[at-base+1:at-base+5]=bytes(4)
    assert len(targets)==4
    return raw.hex(),targets


def key(row):
    return tuple(row[k] for k in ('namespace', 'command', 'mode', 'batch', 'atomic', 'local'))


def compare(post_tag='', output_tag=''):
    rows = []
    arms = {}
    for kind in KINDS:
        sources = {arm: json.loads((wave14.DOC/'instructions'/
                   (f'{arm}-{kind}' + ('-'+post_tag if arm == 'post' and post_tag else ''))/
                   'counts.json').read_text())
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
    stem = 'instruction-comparison' + ('-'+output_tag if output_tag else '')
    wave14.save(wave14.DOC/(stem+'.json'), result)
    lines = ['# Serverless instruction census', '',
        'Finite command scopes; executable instructions include outlined STL and Lua. Shared libraries, fixture glue and synthetic clock calls are excluded. No rate or timing claim.', '',
        '| Kind | Namespace | Command | Mode | Batch | Atomic | Read-local | PRE | POST | Added |',
        '|---|---|---|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append('| '+' | '.join(map(str, (r['kind'], *r['cell'], r['pre'], r['post'], r['added'])))+' |')
    (wave14.DOC/(stem+'.md')).write_text('\n'.join(lines)+'\n')
    print('cells', len(rows), 'GET/SET/INCR positive deltas', len(result['get_set_incr_added']))


def binding(job):
    arm, kind, ns, tag = job
    audit = wave14.references()
    folder = wave14.DOC/'instructions'/(f'{arm}-{kind}' + ('-'+tag if tag else ''))
    build = json.loads((folder/(ns+'-build.json')).read_text())
    probe = Path(build['link'][build['link'].index('-o')+1])
    server = wave14.PRE/'build/tomokv' if arm == 'pre' else wave14.ROOT/'build/tomokv'
    assert wave14.sha(probe) == build['probe_sha256']
    assert wave14.sha(server) == build['server_sha256']
    production, fixture = audit.inventory(server), audit.inventory(probe)
    names = set()
    sites = {}
    for row in json.loads((folder/'counts.json').read_text())['rows']:
        if row['namespace'] == ns:
            names.update(audit.audit.canonical(n) for n in row['functions'])
            path=folder/('-'.join(map(str, key(row)))+'.json.sites.gz')
            with gzip.open(path, 'rt') as stream:
                for pc, count in json.load(stream)['sites'].items():
                    address=int(pc,16)
                    sites[address]=sites.get(address,0)+count
    addresses=sorted(sites)
    rows = []
    for name in sorted(names):
        before = production['groups'].get(name, [])
        after = fixture['groups'].get(name, [])
        # Bind actual executed PCs, not another clone with the same local name.
        # A fixture can emit an unused extra clone into an otherwise equal group.
        entered=[]
        for body in after:
            start=int(body['address'],16)
            lo=bisect.bisect_left(addresses,start)
            hi=bisect.bisect_left(addresses,start+body['size'])
            if hi>lo:
                entered.append(dict(body, instructions=sum(sites[pc] for pc in addresses[lo:hi])))
        matches=bool(entered) and {r['digest'] for r in entered} <= {r['digest'] for r in before}
        if name.endswith('::[asm .rlfence]'):
            matches=rlfence(server)==rlfence(probe)
        rows.append(dict(name=name, equal=matches,
            server_digests=[r['digest'] for r in before], entered_bodies=entered))
    result = dict(arm=arm, kind=kind, namespace=ns, server_sha256=production['sha256'],
        probe_sha256=fixture['sha256'], entered_groups=len(rows),
        matched=sum(r['equal'] for r in rows), unmatched=[r for r in rows if not r['equal']])
    wave14.save(wave14.DOC/('scope-binding'+('-'+tag if tag else ''))/
                f'{arm}-{kind}-{ns}.json', result)
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('phase', choices=('compare','bind'))
    p.add_argument('--arm', choices=('pre','post','both'), default='both')
    p.add_argument('--tag', default='', help='Preserve an earlier census and binding attempt')
    a=p.parse_args()
    if a.phase == 'compare': compare(a.tag, a.tag)
    else:
        arms=('pre','post') if a.arm=='both' else (a.arm,)
        with ProcessPoolExecutor(max_workers=6) as pool:
            rows=list(pool.map(binding, [(arm,kind,ns,a.tag if arm == 'post' else '')
                for arm in arms for kind in KINDS for ns in ('normal','db0')]))
        wave14.save(wave14.DOC/(f'scope-binding-{a.arm}'+('-'+a.tag if a.tag else '')+'.json'), rows)
        print([(r['arm'],r['kind'],r['namespace'],len(r['unmatched'])) for r in rows])


if __name__ == '__main__': main()
