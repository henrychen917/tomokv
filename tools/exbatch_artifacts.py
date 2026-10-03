#!/usr/bin/env python3
"""Offline EX1/EX3/EX6 PAD-A construction and verification. Never runs a server.

The non-allocated .exbatch_pad table records compiler-visible asm-goto edges.
Each five-byte NOP becomes a rel32 jump to the PRE body at the recorded target.
Every function, object, section, instruction outside these five bytes, entry
point and program header retains POST's identity. Subsets permit attribution.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

from lbstall_artifacts import Elf
from rlfence_artifacts import instructions, tables
from ttlstate_proof import program_headers

GROUPS = {'all': {1, 3, 6, 30}, 'ex1': {1}, 'ex3': {3, 30},
          'ex6': {6}, 'watch-no-update': {30}, 'watch-old-loads': {3}}
NOP = bytes.fromhex('0f1f440000')


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n')


def offset(elf, address, size):
    for section in elf.sections:
        if section[2] & 4 and section[3] <= address and address + size <= section[3] + section[5]:
            return section[4] + address - section[3]
    raise AssertionError('control address is outside executable sections')


def plan(source, group):
    elf = Elf(source)
    section = elf.sections[elf.names.index('.exbatch_pad')]
    assert not section[2] & 2, 'control table must not consume mapped memory'
    raw = elf.section_data(elf.names.index('.exbatch_pad'))
    assert raw and len(raw) % 24 == 0, 'control record width'
    records = list(struct.iter_unpack('<QQQ', raw))
    assert len({a for a, _, _ in records}) == len(records), 'duplicate patch site'
    assert {tag for _, _, tag in records} == GROUPS['all'], 'complete EX item inventory'
    asm = subprocess.check_output(['objdump', '-dw', str(source)], text=True)
    code = {a: (b, text) for a, b, text, _ in instructions(asm)}
    functions = [s for s in elf.symbols if s['info'] & 15 == 2 and s['size']]
    patches = []
    for at, target, tag in sorted(records):
        assert code[at][0] == NOP, 'record must point to one complete five-byte NOP'
        assert target in code, 'legacy destination must be an instruction boundary'
        assert at != target, 'legacy destination is not the patch site'
        here = offset(elf, at, 5)
        assert elf.data[here:here + 5] == NOP
        owners = sorted(s['name'] for s in functions if s['value'] <= at < s['value'] + s['size'])
        assert owners, 'every site must belong to a defined function'
        if tag in GROUPS[group]:
            patches.append(dict(address=at, offset=here, target=target, item=tag,
                                before=NOP.hex(), after=(b'\xe9' + struct.pack('<i', target-at-5)).hex(),
                                functions=owners))
    return dict(kind='A: PRE behaviour with exact POST text size and function layout',
                group=group, source_sha256=hashlib.sha256(elf.data).hexdigest(),
                inventory=dict(Counter(tag for _, _, tag in records)), patches=patches)


def verify(source, candidate, group, out=None):
    expected = plan(source, group)
    before, after = Elf(source), Elf(candidate)
    assert before.sections == after.sections, 'section layout changed'
    assert before.symbols == after.symbols, 'function/symbol address table changed'
    assert before.data[16:32] == after.data[16:32] and program_headers(before) == program_headers(after), \
        'entry or program mappings changed'
    restored = bytearray(after.data)
    for patch in expected['patches']:
        at = patch['offset']
        assert after.data[at:at+5].hex() == patch['after'], 'required retarget absent or wrong'
        restored[at:at+5] = bytes.fromhex(patch['before'])
    assert bytes(restored) == before.data, 'unplanned byte changed'
    if out:
        post = tables(before, out, 'POST')
        pad = tables(after, out, 'PAD-A')
        assert post['function_table_sha256'] == pad['function_table_sha256']
        assert post['section_table_sha256'] == pad['section_table_sha256']
        for file in out.glob('*.tsv'):
            with gzip.GzipFile(str(file)+'.gz', 'wb', mtime=0) as stream: stream.write(file.read_bytes())
            file.unlink()
        save(out/'proof.json', dict(post=post, pad=pad, kind=expected['kind'], group=group,
                                   patches=len(expected['patches']), all_other_bytes_equal=True,
                                   every_function_address_and_size_equal=True,
                                   entry_program_headers_and_sections_equal=True))
    return expected


def pad(source, destination, group, out):
    expected = plan(source, group)
    save(out/'planned-retargets.json', expected)  # Freeze the plan before mutation.
    raw = bytearray(Path(source).read_bytes())
    for patch in expected['patches']:
        at = patch['offset']; raw[at:at+5] = bytes.fromhex(patch['after'])
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw); destination.chmod(0o755)
    verify(source, destination, group, out)
    rows = []
    for kind in ('missing-patch', 'unplanned-byte', 'function-address'):
        broken = bytearray(raw)
        if kind == 'missing-patch':
            at = expected['patches'][0]['offset']; broken[at:at+5] = NOP
            message = 'required retarget absent or wrong'
        elif kind == 'unplanned-byte':
            elf = Elf(source)
            at = offset(elf, expected['patches'][0]['target'], 1)
            assert all(not p['offset'] <= at < p['offset']+5 for p in expected['patches'])
            broken[at] ^= 1; message = 'unplanned byte changed'
        else:
            elf = Elf(source)
            table, index = next((t, i) for t, symbols in elf.tables.items()
                                for i, s in enumerate(symbols) if elf.sections[t][1] == 2 and
                                s['info'] & 15 == 2 and s['size'] and 0 < s['sec'] < len(elf.sections))
            at = elf.sections[table][4] + index * elf.sections[table][9] + 8
            struct.pack_into('<Q', broken, at, struct.unpack_from('<Q', broken, at)[0] + 1)
            message = 'function/symbol address table changed'
        file = destination.parent / (kind + '.NEVER-RUN')
        file.write_bytes(broken); file.chmod(0o600)
        try:
            verify(source, file, group)
        except AssertionError as error:
            assert str(error) == message, (kind, str(error))
            rows.append(dict(control=kind, rejected=True, reason=str(error), executed=False))
        else:
            raise AssertionError('verifier accepted ' + kind)
        file.unlink()
    save(out/'negative-controls.json', rows)
    print(f'PASS exbatch PAD-A {group}: {len(expected["patches"])} sites; exact layout; three verifier controls')


def main():
    assert os.sched_getaffinity(0) <= set(range(112, 128)), 'pin offline work to 112-127'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['pad', 'verify'])
    parser.add_argument('source', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--group', choices=GROUPS, default='all')
    args = parser.parse_args()
    if args.action == 'pad': pad(args.source, args.candidate, args.group, args.out)
    else: verify(args.source, args.candidate, args.group, args.out)


if __name__ == '__main__': main()
