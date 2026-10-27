#!/usr/bin/env python3
"""Verify the exact constant loads and bounded switches left by strict normalization."""
import functools
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys

import identity

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 80)))
sys.path.insert(0, str(ROOT / 'tools'))
from lbstall_artifacts import Elf

OUT = ROOT / 'docs/wave8b'
audit = identity.audit


@functools.lru_cache()
def elf(path):
    return Elf(path)


def readonly(path, target, size):
    binary = elf(path)
    sections = [section for section in binary.sections if section[1] == 1 and
                section[2] & 2 and not section[2] & 5 and
                section[3] <= target <= section[3] + section[5] - size]
    section, = sections
    for reloc in binary.sections:
        if reloc[1] not in (4, 9):
            continue
        for position in range(reloc[4], reloc[4] + reloc[5], reloc[9]):
            at, = struct.unpack_from('<Q', binary.data, position)
            assert not target - 7 <= at < target + size, 'loader relocation overlaps the literal'
    offset = section[4] + target - section[3]
    return binary.data[offset:offset + size]


def site(path, name, address, offset):
    info, = [row for row in identity.inventory(path)['groups'][name] if int(row['address'],16) == address]
    raw = audit.run('objdump', '-d', '-w', '--start-address=' + str(address),
                    '--stop-address=' + str(address + info['size']), path)
    instructions = {}
    for line in raw.splitlines():
        if match := audit.INSTRUCTION.match(line):
            instructions[int(match[1],16)] = ' '.join(match[3].split())
    at = address + offset
    asm = instructions[at]
    reference, = list(audit.REFERENCE.finditer(asm))
    target = int(reference[1],16)
    if re.fullmatch(r'mov -?0x[0-9a-f]+\(%rip\),%rax # [0-9a-f]+ <[^<>]+>', asm):
        return dict(kind='immutable 64-bit load', value_hex=readonly(path,target,8).hex())

    external = '::kvobj_external_bytes(' in name
    assert external or '::kvobj_free_with_capacity(' in name, name
    source, base = ('rdi','rcx') if external else ('rbx','rdx')
    assert re.fullmatch(r'lea -?0x[0-9a-f]+\(%rip\),%'+base+r' # [0-9a-f]+ <[^<>]+>',asm)
    addresses = sorted(instructions)
    index = addresses.index(at)
    before = [instructions[x] for x in addresses[index-4:index]]
    assert before[0] == f'cmpb $0x5,(%{source})', before
    assert before[1] == ('mov %rdi,%rdx' if external else 'mov 0x8(%rdx,%rax,1),%r12'), before
    assert before[2].startswith('ja '), before
    default, = list(audit.REFERENCE.finditer(before[2]))
    assert int(default[1],16) in instructions
    assert before[3] == f'movzbl (%{source}),%eax', before
    after = [instructions[x] for x in addresses[index+1:index+4]]
    assert after == [f'movslq (%{base},%rax,4),%rax',f'add %{base},%rax','notrack jmp *%rax'],after
    entries = struct.unpack('<6i', readonly(path,target,24))
    destinations = [target + delta for delta in entries]
    assert all(destination in instructions for destination in destinations)
    return dict(kind='six-entry switch, memory-byte bound and reload verified',
                default_offset=int(default[1],16)-address,
                destination_offsets=[destination-address for destination in destinations])


scope = json.loads((OUT / 'scope-identity.json').read_text())['rows']
rows = []
for difference in json.loads((OUT / 'scope-differences.json').read_text()):
    assert difference['same_size'] and difference['encodings_equal']
    row, = [row for row in scope if row['arm']==difference['arm'] and
            row['namespace']==difference['namespace'] and row['probe_sha256']==difference['probe_sha256']]
    name = audit.canonical(difference['name'])
    paths = [row['probe'],row['release']]
    addresses = []
    for path,key in [(row['probe'],'probe_sha256'),(row['release'],'release_sha256')]:
        inventory = identity.inventory(path)
        assert inventory['sha256'] == row[key]
        body, = inventory['groups'][name]
        addresses.append(int(body['address'],16))
    sites = []
    for changed in difference['instruction_differences']:
        offsets = [int(changed[side].split()[0],16) for side in ('probe','release')]
        assert offsets[0] == offsets[1]
        checks = [site(path,name,address,offset) for path,address,offset in zip(paths,addresses,offsets)]
        assert checks[0] == checks[1], (name,checks)
        sites.append(dict(offset=offsets[0],verification=checks[0]))
    assert sites
    rows.append(dict(arm=row['arm'],namespace=row['namespace'],name=name,
                     probe_sha256=row['probe_sha256'],release_sha256=row['release_sha256'],
                     verified=True,sites=sites))
result = dict(normalizer='tests/reorder_noop.py unchanged; this supplements its unresolved operand labels',
              differences_sha256=hashlib.sha256((OUT/'scope-differences.json').read_bytes()).hexdigest(),
              function_instances=len(rows),sites=sum(len(row['sites']) for row in rows),rows=rows)
(OUT/'scope-relocations.json').write_text(json.dumps(result,indent=2)+'\n')
print('Verified',result['function_instances'],'function instances and',result['sites'],'relocated operands',flush=True)
