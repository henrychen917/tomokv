#!/usr/bin/env python3
"""Preserve the complete scatter function inventory and both disassemblies.

Canonical equality is exact apart from the ccfix audit's named relocations.
A changed body is deliberately not declared cost-neutral by this inventory;
its reachable ordinary paths still need the accompanying instruction review.
No server, workload, or performance instrument is started.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

from ccfix_audit import audit

PATTERN = re.compile(r'::(?:xshard_|ScatterState::|ScatterArenaPool::)|'
                     r'::(?:free_state_contents|free_state_key_anchors|finish_phase[12]|'
                     r'publish_phase2|publish_sort_deref|prepare_sort_deref|finish_sort_deref)\b')


def bodies(path):
    result = {}
    symbol = None
    for line in subprocess.check_output(['objdump', '-drw', str(path)], text=True).splitlines():
        match = re.match(r'^[0-9a-f]+ <(.+)>:$', line)
        if match:
            symbol = match[1]
            result[symbol] = [line]
        elif symbol and re.match(r'\s*[0-9a-f]+:', line):
            result[symbol].append(line)
        elif line.startswith('Disassembly of section '):
            symbol = None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('pre', type=Path)
    parser.add_argument('post', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    rows = []
    objects = []
    for prefix in ('', 'db0/'):
        obj = prefix + 'src/cmd/xshard.o'
        before, after = audit.Elf(args.pre / obj), audit.Elf(args.post / obj)
        old, new = before.functions(), after.functions()
        symbols = sorted(old.keys() | new.keys())
        labels = subprocess.check_output(['c++filt'], input='\n'.join(symbols), text=True).splitlines()
        selected = [(s, n) for s, n in zip(symbols, labels) if PATTERN.search(n)]
        for arm, elf in [('pre', before), ('post', after)]:
            disasm = bodies(elf.path)
            label = ('db0-' if prefix else '') + arm + '.asm.gz'
            with gzip.open(args.output / label, 'wt') as out:
                for symbol, name in selected:
                    if symbol in disasm:
                        out.write('\n// ' + name + '\n' + '\n'.join(disasm[symbol]) + '\n')
        objects.append(dict(object=obj,
                            pre_sha256=hashlib.sha256(before.path.read_bytes()).hexdigest(),
                            post_sha256=hashlib.sha256(after.path.read_bytes()).hexdigest()))
        for symbol, name in selected:
            a, b = old.get(symbol), new.get(symbol)
            rows.append(dict(object=obj, symbol=symbol, name=name,
                             pre_size=a['size'] if a else 0,
                             post_size=b['size'] if b else 0,
                             equal=bool(a and b and before.canonical(a) == after.canonical(b))))
    (args.output / 'inventory.json').write_text(json.dumps(dict(objects=objects, functions=rows), indent=2)+'\n')
    summary = dict(functions=len(rows), equal=sum(r['equal'] for r in rows),
                   changed=sum(not r['equal'] for r in rows))
    (args.output / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
