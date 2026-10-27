#!/usr/bin/env python3
"""Explain strict fixture/release differences without changing the gate normalizer."""
import bisect
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess

import identity

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 80)))
audit = identity.audit
OUT = ROOT / 'docs/wave8b'


def bodies_for_path(job):
    path, required = job
    out = ROOT / 'build/wave8b/scope-differences'
    out.mkdir(exist_ok=True)
    binary = audit.Binary(path, out, literal_pools=True)
    literals = audit.LiteralPools(path, audit.run('nm', '-S', '--defined-only', path))
    addresses = sorted(binary.instructions)
    result = {}
    for name, address in required:
        original, = [item for item in binary.groups[name] if item['addr'] == address]
        size = original['size']
        selected = addresses[bisect.bisect_left(addresses, address):bisect.bisect_left(addresses, address+size)]
        switch_first, tables = [], []
        for index, at in enumerate(selected):
            raw, asm = binary.instructions[at]
            literal = literals.label(asm)
            switch = literals.jump_label(index, selected, binary.instructions, address, size)
            normalized = audit.normalize_asm(asm, address, size, binary.demangle, binary.address_name, switch or literal)
            switch_first.append(f'{at-address:04x} [{len(raw):2}] ' + ' '.join(normalized.split()))
            if switch and literal:
                tables.append(dict(offset=at-address, literal=literal, verified_targets=switch))
        result[str(address)] = dict(strict=original['ins'], switch_first=switch_first,
                                    encodings=original['encodings'], tables=tables)
    (out/(Path(path).name+'.'+binary.sha256[:12]+'.objdump')).unlink()
    return path, result

source = json.loads((OUT / 'scope-identity.json').read_text())['rows']
needed = {}
for row in source:
    for difference in row['differences']:
        name = audit.canonical(difference['name'])
        for path in (row['probe'],row['release']):
            inventory = identity.inventory(path)
            candidates = inventory['groups'][name]
            if path == row['probe']:
                candidates = [item for item in candidates if item['address'] == difference['address']]
            body, = candidates
            needed.setdefault(path,set()).add((name,int(body['address'],16)))
with ProcessPoolExecutor(max_workers=6) as pool:
    normalized = dict(pool.map(bodies_for_path, needed.items()))


rows = []
for row in source:
    probe = identity.inventory(row['probe'])
    release = identity.inventory(row['release'])
    for difference in row['differences']:
        name = audit.canonical(difference['name'])
        left, = [item for item in probe['groups'][name] if item['address'] == difference['address']]
        right, = release['groups'][name]
        a = normalized[row['probe']][str(int(left['address'],16))]
        b = normalized[row['release']][str(int(right['address'],16))]
        for details, expected in [(a, left), (b, right)]:
            actual = hashlib.sha256(json.dumps([details['strict'], details['encodings']]).encode()).hexdigest()
            assert actual == expected['digest'], name
        same = left['size'] == right['size'] and a['encodings'] == b['encodings'] and a['switch_first'] == b['switch_first']
        rows.append(dict(arm=row['arm'], namespace=row['namespace'], name=name,
                         probe_sha256=row['probe_sha256'], release_sha256=row['release_sha256'],
                         same_size=left['size'] == right['size'], encodings_equal=a['encodings'] == b['encodings'],
                         all_differences_verified_switch_tables=same,
                         probe_tables=a['tables'], release_tables=b['tables'],
                         instruction_differences=[dict(probe=x, release=y) for x,y in zip(a['strict'],b['strict']) if x != y],
                         unresolved=[] if same else dict(probe=a, release=b)))
(OUT / 'scope-differences.json').write_text(json.dumps(rows, indent=2) + '\n')
for row in rows:
    print(row['arm'], row['namespace'], row['name'], 'switch relocation verified:',
          row['all_differences_verified_switch_tables'], flush=True)
