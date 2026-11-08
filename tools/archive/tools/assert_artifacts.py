#!/usr/bin/env python3
"""Audit stable-assertion ELF changes and make an offline PAD-A behaviour twin.

Never runs a server. A failed narrow-diff proof stays a failure in the receipt;
address operands are not normalized away to manufacture binary identity.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

from lbstall_artifacts import Elf


def instructions(path):
    result = []
    output = subprocess.check_output(['objdump', '-dw', '-j', '.text', str(path)], text=True)
    for line in output.splitlines():
        match = re.match(r'^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2} )+)\s*(.*)', line)
        if match:
            result.append((int(match[1], 16), bytes.fromhex(match[2]), match[3]))
    return result


def failures(code):
    sites = {}
    prefixes = {'function': bytes.fromhex('488d0d'), 'file': bytes.fromhex('488d35'),
                'condition': bytes.fromhex('488d3d'), 'line': bytes.fromhex('ba')}
    for index, (address, raw, text) in enumerate(code):
        if not re.search(r'^call\s+.*<__assert_fail@plt>', text):
            continue
        args = {}
        for insn in reversed(code[max(0, index - 8):index]):
            for name, prefix in prefixes.items():
                if name not in args and insn[1].startswith(prefix) and len(insn[1]) == len(prefix) + 4:
                    args[name] = insn
        assert set(args) == set(prefixes), f'unknown failure block at {address:x}'
        sites[address] = args
    assert len(sites) == 41, f'expected 41 emitted failure blocks, got {len(sites)}'
    return sites


def offset(elf, address):
    for section in elf.sections:
        if section[1] != 8 and section[2] & 2 and section[3] <= address < section[3] + section[5]:
            return section[4] + address - section[3]
    raise AssertionError(f'unmapped address {address:x}')


def string(elf, instruction):
    address, raw, _ = instruction
    target = address + len(raw) + struct.unpack('<i', raw[-4:])[0]
    start = offset(elf, target)
    return elf.data[start:elf.data.index(b'\0', start)]


def layout(elf):
    return {name: (sec[3], sec[5], sec[8]) for name, sec in zip(elf.names, elf.sections)
            if sec[2] & 2}


def audit(pre, post):
    a, b = Elf(pre), Elf(post)
    left, right = instructions(pre), instructions(post)
    af, bf = failures(left), failures(right)
    old, new = {x[0]: x for x in left}, {x[0]: x for x in right}
    changed = [address for address in old.keys() & new.keys() if old[address][1] != new[address][1]]
    assertion_args = {insn[0] for args in af.values() for insn in args.values()}
    outside = sorted(set(changed) - assertion_args)
    differing = []
    for name in a.names:
        if name not in b.names or name.startswith(('.debug', '.note.gnu.build-id')) or name in ('.symtab', '.strtab', '.shstrtab'):
            continue
        ai, bi = a.names.index(name), b.names.index(name)
        if a.sections[ai][1] == 8:
            continue
        if a.section_data(ai) != b.section_data(bi):
            differing.append(name)
    result = dict(allocated_layout_identical=layout(a) == layout(b),
                  instruction_addresses_identical=old.keys() == new.keys(),
                  instruction_lengths_identical=old.keys() == new.keys() and all(len(old[x][1]) == len(new[x][1]) for x in old),
                  failure_calls_identical=af.keys() == bf.keys() and all(old[x][1] == new[x][1] for x in af),
                  failure_blocks=len(af), changed_instructions=len(changed),
                  changed_failure_arguments=len(set(changed) & assertion_args),
                  changed_outside_failure_blocks=len(outside),
                  changed_mnemonics=dict(Counter(old[x][2].split()[0] for x in changed)),
                  differing_sections=differing,
                  outside_examples=[dict(address=hex(x), pre=old[x][2], post=new[x][2]) for x in outside[:10]])
    result['narrow_diff_proof'] = (not outside and differing == ['.text', '.rodata'] and
                                   result['allocated_layout_identical'] and result['instruction_lengths_identical'])
    return result


def pad(pre, post, output):
    a, b = Elf(pre), Elf(post)
    assert Path(output).resolve() not in (Path(pre).resolve(), Path(post).resolve())
    left, right = failures(instructions(pre)), failures(instructions(post))
    assert left.keys() == right.keys()
    candidates = [s for s in b.symbols if 'assertion_rodata_pad' in s['name']]
    assert len(candidates) == 1
    reserve = candidates[0]
    base, capacity = reserve['value'], reserve['size']
    data = bytearray(b.data)
    start = offset(b, base)
    assert data[start:start + capacity] == bytes(capacity)
    strings = sorted({string(a, site[name]) for site in left.values()
                      for name in ('function', 'file', 'condition')})
    cursor, addresses = 0, {}
    for value in strings:
        addresses[value] = base + cursor
        data[start + cursor:start + cursor + len(value) + 1] = value + b'\0'
        cursor += len(value) + 1
    assert cursor <= capacity, f'{cursor} bytes exceed padding capacity {capacity}'
    patches = []
    for call, old in left.items():
        current = right[call]
        for name in ('line', 'function', 'file', 'condition'):
            before, after = old[name], current[name]
            assert before[0] == after[0] and len(before[1]) == len(after[1])
            assert before[1][:-4] == after[1][:-4]
            at = offset(b, after[0]) + len(after[1]) - 4
            replacement = (before[1][-4:] if name == 'line' else
                           struct.pack('<i', addresses[string(a, before)] - after[0] - len(after[1])))
            data[at:at + 4] = replacement
            patches.append((at, at + 4))
    assert len(data) == len(b.data)
    allowed = {i for first, last in patches + [(start, start + capacity)] for i in range(first, last)}
    assert all(x == y or i in allowed for i, (x, y) in enumerate(zip(b.data, data)))
    Path(output).write_bytes(data)
    Path(output).chmod(Path(post).stat().st_mode)
    twin = Elf(output)
    assert twin.sections == b.sections and twin.symbols == b.symbols
    restored = failures(instructions(output))
    for call, old in left.items():
        assert restored[call]['line'][1] == old['line'][1]
        for name in ('function', 'file', 'condition'):
            assert string(twin, restored[call][name]) == string(a, old[name])
    return dict(kind='A: behaviour twin', behavior='PRE assertion diagnostics at POST code and data layout',
                failure_blocks=len(left), diagnostic_strings=len(strings), diagnostic_bytes=cursor,
                pad_capacity=capacity, layout_identical=True,
                post_sha256=hashlib.sha256(b.data).hexdigest(),
                pad_sha256=hashlib.sha256(data).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('audit', 'pad'))
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = (audit(args.pre, args.post) if args.action == 'audit' else
              pad(args.pre, args.post, args.output))
    print(json.dumps(result, indent=2))
    if args.action == 'audit' and not result['narrow_diff_proof']:
        raise SystemExit(1)
