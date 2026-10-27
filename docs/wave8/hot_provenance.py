#!/usr/bin/env python3
"""Resolve the six remaining command-body differences without relaxing the gate.

Only the exact instructions recorded by the strict inventory are accepted.
TLS operands resolve to the same ScriptWorkbench field or its adjacent guard;
read-only operands compare their actual bytes, including the whole small table.
"""
import gzip
import json
import re
import struct
import subprocess
from pathlib import Path
import identity
from lbstall_artifacts import Elf

ROOT = identity.ROOT
paths = {'headline': Path(identity.REFS['headline']), 'post': ROOT / 'build/tomokv'}
inventories = {a: identity.inventory(p) for a, p in paths.items()}
bodies = {a: json.load(gzip.open(ROOT / 'docs/wave8/callsites' / (a + '.json.gz'), 'rt'))
          for a in paths}
elves = {a: Elf(p) for a, p in paths.items()}
tls = {}
symbols = {}
for arm, path in paths.items():
    line = next(l for l in subprocess.check_output(['readelf', '-W', '-l', str(path)], text=True).splitlines()
                if l.lstrip().startswith('TLS'))
    parts = line.split()
    size, align = int(parts[5], 16), int(parts[-1], 16)
    size = (size + align - 1) // align * align
    tls[arm] = {}
    for line in subprocess.check_output(['readelf', '-W', '-s', str(path)], text=True).splitlines():
        words = line.split()
        if len(words) >= 8 and words[3] == 'TLS' and words[-1].endswith('t_script_workbenchE'):
            ns = 'tomo_db0' if 'ZN8tomo_db0' in words[-1] else 'tomo'
            tls[arm][ns] = int(words[1], 16) - size
    symbols[arm] = {}
    for line in subprocess.check_output(['nm', '-S', '--defined-only', str(path)], text=True).splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4:
            symbols[arm][int(parts[0], 16)] = (int(parts[1], 16), parts[3])


def literal(arm, name, instruction, length):
    body, = inventories[arm]['groups'][name]
    offset = int(instruction.split()[0], 16)
    at = int(body['address'], 16) + offset
    text = subprocess.check_output(['objdump', '-dw', '--start-address=' + hex(at),
                                    '--stop-address=' + hex(at + 7), str(paths[arm])], text=True)
    line = next(l for l in text.splitlines() if re.match(r'\s*' + hex(at)[2:] + ':', l))
    target = int(re.search(r'#\s+([0-9a-f]+)', line)[1], 16)
    if length is None:
        length, symbol = symbols[arm][target]
        assert symbol.startswith('CSWTCH.') and length == 4, (symbol, length)
    section, = [s for s in elves[arm].sections if s[2] & 2 and not s[2] & 1 and s[1] != 8
                and s[3] <= target and target + length <= s[3] + s[5]]
    at = section[4] + target - section[3]
    data = elves[arm].data[at:at + length]
    return dict(target=hex(target), size=length, bytes=data.hex())


def prove(name, first, second):
    assert len(first['ins']) == len(second['ins'])
    ns = 'tomo_db0' if 'tomo_db0::' in name else 'tomo'
    changes = []
    for index, (a, b) in enumerate(zip(first['ins'], second['ins'])):
        ea, eb = first['encodings'][index], second['encodings'][index]
        if a == b:
            assert ea == eb
            continue
        if '<rip>' in a:
            assert ea == eb and a.split('#')[0] == b.split('#')[0]
            if 'CSWTCH.' in a:
                assert re.search(r'\] lea <rip>\(%rip\),%(?:rcx|rdx) # <CSWTCH\.\d+>$', a)
                assert re.search(r'\] lea <rip>\(%rip\),%(?:rcx|rdx) # <CSWTCH\.\d+>$', b)
                length = None
            else:
                assert re.search(r'\] mov <rip>\(%rip\),%rax # ', a)
                length = 8
            left, right = literal('headline', name, a, length), literal('post', name, b, length)
            assert left['bytes'] == right['bytes']
            changes.append(dict(index=index, kind='readonly', headline=left, post=right))
            continue
        pattern = r'%fs:(0x[0-9a-f]+)' if '%fs:' in a else r'lea (-0x[0-9a-f]+)\(%rax\),%rsi'
        left, right = re.search(pattern, a), re.search(pattern, b)
        assert left and right and a.replace(left[1], 'TLS') == b.replace(right[1], 'TLS'), (a, b)
        values = [int(m[1], 16) for m in (left, right)]
        values = [v - (1 << 64) if v >= (1 << 63) else v for v in values]
        fields = [value - tls[arm][ns] for arm, value in zip(paths, values)]
        assert fields[0] == fields[1] and fields[0] in (-56, 0, 8), fields
        if '%fs:' not in a:
            assert fields[0] == 0
            assert first['ins'][index-4].endswith('mov %fs:0x0,%rax')
            assert second['ins'][index-4].endswith('mov %fs:0x0,%rax')
        encoded = [' '.join(f'{x:02x}' for x in struct.pack('<i', v)) for v in values]
        assert ea.count(encoded[0]) == eb.count(encoded[1]) == 1
        assert ea.replace(encoded[0], 'TLS') == eb.replace(encoded[1], 'TLS')
        changes.append(dict(index=index, kind='TLS', field=fields[0],
                            headline=values[0], post=values[1]))
    assert changes
    return changes


rows = json.loads((ROOT / 'docs/wave8/identity/changed-bodies.json').read_text())
names = [r['name'] for r in rows if r['command_hot'] and not r['matches']]
assert len(names) == 6
proofs = {}
for name in names:
    a, = bodies['headline'][name]
    b, = bodies['post'][name]
    changes = prove(name, a, b)
    broken = json.loads(json.dumps(b))
    broken['encodings'][0] += ' 90'
    try:
        prove(name, a, broken)
    except AssertionError:
        opcode_rejected = True
    else:
        opcode_rejected = False
    assert opcode_rejected
    proofs[name] = dict(changes=changes, changed_opcode_rejected=opcode_rejected)
result = dict(tls_workbench_offsets=tls, bodies=proofs,
              scope='Supplemental operand proof only; the strict identity inventory remains unchanged.')
(ROOT / 'docs/wave8/identity/hot-provenance.json').write_text(json.dumps(result, indent=2) + '\n')
print('Six command wrappers: exact instructions except verified equal read-only bytes and relocated TLS fields.')
