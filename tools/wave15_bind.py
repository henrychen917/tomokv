#!/usr/bin/env python3
"""Bind counted PCs to the frozen server bodies before pruning probe binaries."""
import bisect
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
import os
from pathlib import Path
import wave15
from wave14_summary import rlfence

KINDS = ('ordinary', 'scripts', 'session', 'other', 'parser', 'tracked-scripts', 'tls', 'errors')

def binding(job):
    arm, kind, ns = job
    audit = wave15.references()
    tag = ('-final1' if kind == 'parser' else '-final') if arm == 'post' else ''
    folder = wave15.DOC/'instructions'/(arm+'-'+kind+tag)
    build = json.loads((folder/(ns+'-build.json')).read_text())
    probe = Path(build['link'][build['link'].index('-o')+1])
    server = {'pre':wave15.PRE/'build/tomokv',
              'headline':wave15.BUILD/'headline-source/build/tomokv',
              'post':wave15.BUILD/'POST-1babe0d58a-final'}[arm]
    assert wave15.sha(probe) == build['probe_sha256']
    assert wave15.sha(server) == build['server_sha256']
    production, fixture = audit.inventory(server), audit.inventory(probe)
    names, sites = set(), {}
    for row in json.loads((folder/'counts.json').read_text())['rows']:
        if row['namespace'] != ns: continue
        names.update(audit.audit.canonical(name) for name in row['functions'])
        key = '-'.join(str(row[k]) for k in ('namespace','command','mode','batch','atomic','local'))
        with gzip.open(folder/(key+'.json.sites.gz'), 'rt') as stream:
            for pc, count in json.load(stream)['sites'].items():
                address = int(pc, 16); sites[address] = sites.get(address, 0)+count
    addresses = sorted(sites); rows = []
    for name in sorted(names):
        before = production['groups'].get(name, [])
        entered = []
        for body in fixture['groups'].get(name, []):
            start = int(body['address'], 16)
            lo, hi = bisect.bisect_left(addresses,start), bisect.bisect_left(addresses,start+body['size'])
            if hi > lo: entered.append(dict(body,instructions=sum(sites[a] for a in addresses[lo:hi])))
        equal = bool(entered) and {r['digest'] for r in entered} <= {r['digest'] for r in before}
        if name.endswith('::[asm .rlfence]'): equal = rlfence(server) == rlfence(probe)
        rows.append(dict(name=name,equal=equal,server_digests=[r['digest'] for r in before],entered_bodies=entered))
    record = dict(arm=arm,kind=kind,namespace=ns,server_sha256=production['sha256'],
        probe_sha256=fixture['sha256'],entered_groups=len(rows),matched=sum(r['equal'] for r in rows),
        unmatched=[r for r in rows if not r['equal']])
    wave15.save(wave15.DOC/'scope-binding'/(arm+'-'+kind+'-'+ns+'.json'),record)
    print(arm,kind,ns,record['matched'],'/',record['entered_groups'],flush=True)
    return record

if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(16,64))
    jobs = [(a,k,n) for a in ('pre','headline','post') for k in KINDS for n in ('normal','db0')]
    with ProcessPoolExecutor(4) as pool: rows = list(pool.map(binding,jobs))
    wave15.save(wave15.DOC/'scope-binding.json',rows)
