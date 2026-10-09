#!/usr/bin/env python3
"""Account for every sidecar body delta, retaining instruction/relocation diffs."""
from bisect import bisect_left
from collections import Counter, defaultdict
import difflib
import gzip
import json
from pathlib import Path
import re
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'tools'))
from lbstall_artifacts import Elf

rows = json.loads((root / 'docs/deadswitch/06-bodies/changed-bodies.json').read_text())
by_object = defaultdict(list)
for row in rows:
    by_object[row['object']].append(row)

def disassemble(path):
    sections, section = defaultdict(list), None
    output = subprocess.check_output(['objdump', '-drw', str(path)], text=True)
    for line in output.splitlines():
        if line.startswith('Disassembly of section '):
            section = line[len('Disassembly of section '):-1]
        else:
            match = re.match(r'\s*([0-9a-f]+):\s+(.*)', line)
            if match:
                sections[section].append((int(match[1], 16), match[2]))
    return {name: (items, [at for at, _ in items]) for name, items in sections.items()}

def body(elf, index, symbol):
    if not symbol:
        return []
    items, addresses = index.get(elf.names[symbol['sec']], ([], []))
    first = bisect_left(addresses, symbol['value'])
    last = bisect_left(addresses, symbol['value'] + symbol['size'])
    return [f'{at-symbol["value"]:05x}: {text}\n' for at, text in items[first:last]]

def reason(row):
    n = row['name']
    if 'ExpireIndex::' in n:
        return 'index', ('Deadline-sidecar table layout: add int64 deadline storage, offset state bytes, '
                         'carry deadlines through insert/migration, and update allocation/accounting.')
    if 'FlatStore::deadline(' in n:
        return 'deadline', ('Owner deadline lookup adds the sidecar probe and retains inline fallback '
                            'for snapshot/atomic versions and missing entries.')
    if 'FlatStore::track_expire(' in n:
        return 'refresh', ('Index writes retain deadline values; failed sidecar insertion erases stale '
                           'state before falling back to the immutable object deadline.')
    if not row['pre_size'] or not row['post_size']:
        return 'outline', ('Selector-triggered GCC outlining: emitted only in ' +
                          ('POST' if row['post_size'] else 'PRE') +
                          '; caller/clone changes are included in this inventory.')
    if re.search(r'FlatStore::(?:find|live_or_expire|active_expire|random_volatile|choose_victim|scan_home)', n):
        return 'ttl-consumer', ('Lookup/reap/scan/eviction path consumes changed deadline/index operations; '
                                'the compiler also changes their inline/outline placement.')
    if re.search(r'FlatStore::(?:insert|erase|atomic|snapshot|clear|persist|set_expire|make_room)', n):
        return 'store-mutator', ('Owning-store path inserts/erases/copies TTL state or calls regenerated '
                                 'store helpers; sidecar deadlines now survive the index operations.')
    if 'publish_keyspace_sample' in n or 'cmd_info(' in n:
        return 'accounting', ('Compiled storage/accounting dependencies change with the larger expiry '
                              'index allocation, including inlining and exception cleanup.')
    return 'codegen', ('Source body is unchanged; this selector-only build changes compiler inlining, '
                       'cloning, constant/relocation selection or calls in its translation unit. '
                       'The exact instruction/relocation delta is retained; no neutrality claim.')

diffs = []
for relative, group in sorted(by_object.items()):
    a, b = [Elf(root / 'build/deadswitch' / arm / relative)
            for arm in ('ttl-inline', 'ttl-sidecar')]
    old, new = a.functions(), b.functions()
    ai, bi = disassemble(a.path), disassemble(b.path)
    for row in group:
        key = row['symbol']
        before, after = body(a, ai, old.get(key)), body(b, bi, new.get(key))
        assert before or after, row
        category, explanation = reason(row)
        row['category'], row['explanation'] = category, explanation
        row['pre_instruction_lines'], row['post_instruction_lines'] = len(before), len(after)
        diffs.append(f'\nOBJECT {relative}\nSYMBOL {key}\nNAME {row["name"]}\nWHY {explanation}\n')
        delta = list(difflib.unified_diff(before, after, fromfile='inline', tofile='sidecar'))
        # A raw-equal body can still refer to changed constant data behind an unchanged relocation.
        diffs.extend(delta or ['Instruction/relocation text unchanged; canonical referenced constant/target differs.\n'])

out = root / 'docs/deadswitch'
(out / '06-changed-bodies.json.gz').write_bytes(gzip.compress((json.dumps(rows, indent=2)+'\n').encode(), mtime=0))
(out / '06-body-diffs.txt.gz').write_bytes(gzip.compress(''.join(diffs).encode(), mtime=0))
summary = Counter(row['category'] for row in rows)
(out / '06-change-categories.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(dict(total=len(rows), categories=summary)))
