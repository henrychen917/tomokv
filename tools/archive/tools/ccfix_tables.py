#!/usr/bin/env python3
"""Supplement the linked checker with exact data/case-target proofs; never executes an arm."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import struct
from ccfix_audit import audit


def read_at(elf, address, size):
    section = next(s for s in elf.sections if s[1] != 8 and
                   s[3] <= address and address + size <= s[3] + s[5])
    offset = section[4] + address - section[3]
    return elf.data[offset:offset + size]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('linked', type=Path)
    parser.add_argument('objects', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    linked = json.loads((args.linked / 'audit.json').read_text())
    rows = json.load(gzip.open(args.objects / 'bodies.json.gz', 'rt'))
    binaries = [audit.Elf(root / 'tomokv') for root in (args.pre, args.post)]
    for label, binary in zip(('pre', 'post'), binaries):
        assert hashlib.sha256(binary.data).hexdigest() == linked[label + '_sha256']
    result = []
    for row in linked['rows']:
        if row['equal']:
            continue
        matches = [r for r in rows if r['name'] == row['name']]
        assert len(matches) == 1 and matches[0]['equal'], row['name']
        record = matches[0]
        # Only a single seven-byte RIP-relative LEA's data label may differ.
        changes = [s for s in (args.linked / row['diff']).read_text().splitlines()
                   if s[:1] in ('-', '+') and not s.startswith(('---', '+++'))]
        assert len(changes) == 2
        lea = [re.fullmatch(r'[+-]([0-9a-f]+) \[ 7\] lea (.*)', s) for s in changes]
        assert all(lea) and lea[0][1] == lea[1][1]
        off = int(lea[0][1], 16)
        values = []
        for root, binary in zip((args.pre, args.post), binaries):
            obj = audit.Elf(root / record['object'])
            fn = obj.functions()[record['symbol']]
            relocation = next(z for z in obj.relocs[fn['sec']]
                              if z[0] == fn['value'] + off + 3)
            _, kind, symbol, addend = relocation
            function = binary.functions()[record['symbol']]
            instruction = read_at(binary, function['value'] + off, 7)
            assert instruction[:3] in (b'\x48\x8d\x15', b'\x4c\x8d\x3d')
            address = function['value'] + off + 7 + struct.unpack('<i', instruction[3:])[0]
            if 'xshard_execute' in row['name']:
                value = read_at(binary, address, 5).hex()
                assert value == obj.target(symbol, addend, kind)[1] == '0000010405'
                values.append(dict(table_hex=value))
            else:
                assert 'IoLoop::run_loop<' in row['name']
                size = obj.sections[symbol['sec']][5]
                assert size > 0 and size % 4 == 0
                data = read_at(binary, address, size)
                offsets = [address + x - function['value']
                           for x in struct.unpack('<' + 'i' * (size // 4), data)]
                assert all(0 <= x < function['size'] for x in offsets)
                table = dict(sec=symbol['sec'], value=0, size=size)
                values.append(dict(case_offsets=offsets,
                                   canonical_repr=repr(obj.canonical(table))))
        assert values[0] == values[1], row['name']
        result.append(dict(name=row['name'], object=record['object'], body_equal=True,
                           table_equal=True, **values[0]))
    assert len(result) == 5, 'this receipt must account for exactly the five ccfix label changes'
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('PASS: five label differences have identical switch values or case destinations')


if __name__ == '__main__':
    main()
