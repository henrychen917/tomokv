#!/usr/bin/env python3
"""Explain, without weakening r7shadow_noop, its three unnamed jump-table moves."""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
from lbstall_artifacts import Elf


def inspect(binary, inventory, side):
    elf = Elf(binary)
    anchor = next(s for s in elf.symbols if s['name'] == '_IO_stdin_used')
    section = elf.sections[anchor['sec']]
    functions = elf.functions()
    names = list(functions)
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
    mapping = dict(zip(labels, names))
    rows = []
    for diff in sorted(inventory.glob('*.diff')):
        text = diff.read_text()
        if '\n--- PRE\n' not in text:
            continue
        name = text.splitlines()[0].removeprefix('Function: ')
        before = diff.with_suffix('.diff.pre').read_text()
        after = diff.with_suffix('.diff.post').read_text()
        pattern = r'_IO_stdin_used\+0x([0-9a-f]+)'
        assert re.sub(pattern, 'TABLE', before) == re.sub(pattern, 'TABLE', after), name
        body = before if side == 'PRE' else after
        offsets = re.findall(pattern, body)
        assert len(offsets) == 1 and 'lea <rip>(%rip),%r15' in body, name
        # Establish this is the bounded 18-entry relative UrKind switch, not a string
        # or an arbitrary data address. Inspect the existing disassembler output.
        assert 'cmp $0x11,%al | 3c 11' in body, name
        assert 'movslq (%r15,%rax,4),%rax | 49 63 04 87' in body, name
        assert 'add %r15,%rax | 4c 01 f8' in body, name
        assert 'notrack jmp *%rax | 3e ff e0' in body, name
        address = anchor['value'] + int(offsets[0], 16)
        at = address - section[3]
        raw = elf.section_data(anchor['sec'])[at:at+72]
        fn = functions[mapping[name]]
        targets = [address+x-fn['value'] for x in struct.unpack('<18i', raw)]
        assert all(0 <= t < fn['size'] for t in targets), name
        rows.append(dict(body=name, anchor_offset=int(offsets[0], 16),
                         table_bytes=72, function_relative_targets=targets))
    assert len(rows) == 3, 'unexpected linked-diff inventory'
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path); p.add_argument('post', type=Path)
    p.add_argument('inventory', type=Path); p.add_argument('output', type=Path)
    a = p.parse_args()
    before, after = inspect(a.pre, a.inventory, 'PRE'), inspect(a.post, a.inventory, 'POST')
    for x, y in zip(before, after):
        assert x['body'] == y['body'] and x['function_relative_targets'] == y['function_relative_targets']
    result = dict(PRE=before, POST=after, verdict='Only three unnamed rodata anchors move; all 54 jump destinations retain their exact function-relative offsets. Existing normalizer unchanged.')
    a.output.write_text(json.dumps(result, indent=2)+'\n')
    print('PASS three table relocations; 54/54 destinations identical')


if __name__ == '__main__':
    main()
