#!/usr/bin/env python3
"""Prove linker selection for changed/new weak copies; no opcode masking or execution."""
import argparse
import json
from pathlib import Path
import re
from ccfix_audit import audit

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('pre', type=Path)
    p.add_argument('post', type=Path)
    p.add_argument('report', type=Path)
    args = p.parse_args()
    inventory = json.loads((args.report / 'changed-bodies.json').read_text())
    roots = [args.pre.resolve(), args.post.resolve()]
    input_roots = [roots[0], ROOT / 'build']
    records, binaries, cache = [], [], {}
    for root, input_root in zip(roots, input_roots):
        rows = {}
        pattern = r'^ (\.text\S*)\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(\S+\.o)$'
        for section, address, size, source in re.findall(
                pattern, (root / 'tomokv.map').read_text(), re.M):
            path = Path(source).resolve()
            if path.is_relative_to(input_root):
                rows.setdefault(section, []).append(dict(address=int(address, 16),
                    size=int(size, 16), object=str(path.relative_to(input_root))))
        records.append(rows)
        binaries.append(audit.Elf(root / 'tomokv').functions())

    def get(arm, relative):
        key = (arm, relative)
        if key not in cache:
            path = roots[arm] / relative
            cache[key] = audit.Elf(path) if path.exists() else None
        return cache[key]

    receipts = []
    for row in inventory:
        symbol = row['symbol']
        if row['object'].endswith('/aclkeys.o'):
            continue
        pair = [get(arm, row['object']) for arm in (0, 1)]
        copies = [elf.functions().get(symbol) if elf else None for elf in pair]
        if not any(copy and copy['info'] >> 4 == 2 for copy in copies):
            continue
        selections = []
        for arm, (elf, copy) in enumerate(zip(pair, copies)):
            reference = copy or copies[1 - arm]
            origin = elf if copy else pair[1 - arm]
            section = origin.names[reference['sec']]
            choices = [entry for entry in records[arm].get(section, []) if entry['address']]
            selected = None
            if len(choices) == 1 and symbol in binaries[arm]:
                entry = choices[0]
                linked = binaries[arm][symbol]
                if linked['value'] == entry['address'] and linked['size'] == entry['size']:
                    winner = get(arm, entry['object'])
                    definition = winner.functions().get(symbol)
                    if definition:
                        selected = dict(**entry, canonical=winner.canonical(definition))
            selections.append(selected)
        equal = bool(all(selections) and selections[0]['canonical'] == selections[1]['canonical'])
        discarded = bool(all(selections) and all(
            entry['object'] != row['object'] for entry in selections))
        receipts.append(dict(object=row['object'], symbol=symbol, name=row['name'],
                             selected_existing_body_equal=equal,
                             changed_copy_discarded_in_both_arms=discarded,
                             selection=[{k: v for k, v in entry.items() if k != 'canonical'}
                                        if entry else None for entry in selections]))
    result = dict(receipts=receipts,
                  limitation='This records discarded object copies separately; it does not call their object bytes identical.')
    (args.report / 'link-selection.json').write_text(json.dumps(result, indent=2) + '\n')
    for row in receipts:
        print(row['object'], row['name'], 'selected_equal', row['selected_existing_body_equal'],
              'discarded', row['changed_copy_discarded_in_both_arms'])


if __name__ == '__main__':
    main()
