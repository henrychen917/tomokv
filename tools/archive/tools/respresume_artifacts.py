#!/usr/bin/env python3
"""Static objdump inventory, including every local/COMDAT/db0 parser clone.

Counts are instructions in each emitted body, not measured instructions/op.
The full address-keyed inventory avoids collapsing identically named IPA clones.
"""
import argparse
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess


def inspect(binary, output):
    symbols = subprocess.check_output(['nm', '-S', '-C', str(binary)], text=True)
    wanted = []
    for line in symbols.splitlines():
        m = re.match(r'([0-9a-f]+) ([0-9a-f]+) [tTwW] (.*)', line)
        if m and re.search(r'\b(?:resp_parse_t|parse_and_dispatch|r7_parse_and_dispatch)<', m[3]):
            wanted.append((int(m[1], 16), int(m[2], 16), m[3]))
    dump = subprocess.check_output(['objdump', '-dC', '--no-show-raw-insn', str(binary)], text=True)
    insns = {}
    for line in dump.splitlines():
        m = re.match(r'\s*([0-9a-f]+):\s+(\S.*)', line)
        if m:
            insns[int(m[1], 16)] = m[2]
    addresses = sorted(insns)
    rows = []
    for address, size, name in sorted(wanted):
        body = [(at, insns[at]) for at in addresses if address <= at < address + size]
        rows.append(dict(address=hex(address), bytes=size, instructions=len(body), name=name,
                         canary_loads=sum('%fs:0x28' in text and text.startswith('mov') for _, text in body),
                         canary_fail_calls=sum('__stack_chk_fail' in text for _, text in body),
                         instructions_text=[f'{at:x}: {text}' for at, text in body]))
    output.mkdir(parents=True, exist_ok=True)
    meta = dict(binary=str(binary), sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                rows=rows)
    (output / 'disassembly.json.gz').write_bytes(gzip.compress(
        (json.dumps(meta, indent=2) + '\n').encode(), mtime=0))
    with (output / 'disassembly.tsv').open('w') as f:
        f.write('address\tbytes\tstatic_instructions\tcanary_loads\tcanary_fail_calls\tsymbol\n')
        for r in rows:
            f.write('\t'.join(str(r[k]) for k in ('address', 'bytes', 'instructions',
                                                'canary_loads', 'canary_fail_calls', 'name')) + '\n')
    groups = collections.defaultdict(list)
    for row in rows:
        family = re.search(r'\b(resp_parse_t|parse_and_dispatch|r7_parse_and_dispatch)<', row['name'])[1]
        groups[family].append(row)
    for family, members in groups.items():
        print(family, 'clones=', len(members), 'bytes=', sum(x['bytes'] for x in members),
              'static_insns=', sum(x['instructions'] for x in members),
              'canary_loads=', sum(x['canary_loads'] for x in members))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('binary', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    inspect(args.binary, args.output)
