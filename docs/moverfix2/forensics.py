#!/usr/bin/env python3
"""Retain exact compiler excerpts and the immutable source/binary bindings."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/moverfix2'
sha = lambda data: hashlib.sha256(data).hexdigest()
report = {'compiler': subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
          'dumps': []}
for label in ('pre-normal', 'pre-db0', 'normal-128550', 'db0-127250', 'normal-136000'):
    path = ROOT / 'build/moverfix2/trials' / (label + '.085i.inline.gz')
    data = gzip.open(path, 'rb').read()
    lines = data.decode().splitlines()
    ids = {}
    for line in lines:
        if line.startswith('_ZN') and '14xshard_execute' in line and (
                '26atomic_for_each_unique_key' in line or '9FlatStore4scan' in line):
            match = re.search(r'/(\d+) \((atomic_for_each_unique_key.isra|scan.constprop)\)', line)
            if match:
                ids[match[2]] = match[1]
    assert len(ids) == 2
    selected = set()
    for index, line in enumerate(lines):
        for name, number in ids.items():
            key = name + '/' + number
            if line.startswith('Inlining ' + key):
                selected.update(range(max(0, index - 3), min(len(lines), index + 26)))
            if line.startswith('IPA function summary for ' + key):
                selected.update(range(index, index + 9))
            if line.startswith('_ZN') and line.endswith('(' + name + ')') and '/' + number + ' ' in line:
                selected.update(range(index, index + 12))
    text = '\n'.join(f'{i+1}: {lines[i]}'.rstrip() for i in sorted(selected)
                     if not lines[i].startswith('  Calls:')) + '\n'
    excerpt = OUT / (label + '-ipa-excerpts.txt')
    excerpt.write_text(text)
    report['dumps'].append(dict(path=str(path.relative_to(ROOT)), uncompressed_sha256=sha(data),
                                excerpt=str(excerpt.relative_to(ROOT)), clones=ids))

for rel in ('src/store/flatstore_atomic.inc', 'src/cmd/scatter_engine.inc'):
    before = subprocess.check_output(['git', 'show', '8656f9fa9:' + rel], cwd=ROOT)
    after = (ROOT / rel).read_bytes()
    if rel.endswith('scatter_engine.inc'):
        def keys_block(data):
            start = data.index(b'group.scan_cursor = shard.store().scan')
            end = data.index(b'            case Kind::Msetnx:', start)
            return data[start:end]
        before, after = keys_block(before), keys_block(after)
    assert before == after, rel
    report[rel] = dict(compared='whole file' if 'flatstore' in rel else 'KEYS/RANDOMKEY scans',
                       unchanged=True, sha256=sha(after))

rows = []
for path in sorted(OUT.glob('trials-*.json')):
    rows.extend(json.loads(path.read_text()))
report['trials'] = [{k:v for k,v in row.items() if k not in ('command', 'changes')}
                    for row in sorted(rows, key=lambda r:(r['namespace'], r['budget']))]
(OUT / 'forensics.json').write_text(json.dumps(report, indent=2) + '\n')
for path in OUT.glob('*.inline-excerpts.txt'):
    if path.stat().st_size == 0:
        path.unlink()
print('retained', len(report['dumps']), 'compiler excerpts and', len(rows), 'trials')
