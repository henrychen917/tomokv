"""Keep complete strict diffs, object provenance, and the PAD-A residuals."""
import difflib
import gzip
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests'))
from reorder_noop import Binary, canonical

dest = ROOT / 'docs/trackfix/trackfix2/identity'
cache = ROOT / 'build/trackfix/trackfix2-body-details'
cache.mkdir(parents=True, exist_ok=True)
summary = json.loads((dest / 'summary.json').read_text())
changed = summary['changed']
objects = sorted((ROOT / 'build/trackfix/pre-objects').rglob('*.o'))
object_rows = []
owners = {}
for old in objects:
    rel = old.relative_to(ROOT / 'build/trackfix/pre-objects')
    new = ROOT / 'build' / rel
    same = hashlib.sha256(old.read_bytes()).digest() == hashlib.sha256(new.read_bytes()).digest()
    object_rows.append(dict(object=str(rel), byte_identical=same))
    text = subprocess.check_output(['nm', '-C', '--defined-only', str(old)], text=True)
    for line in text.splitlines():
        parts = line.split(maxsplit=2)
        if len(parts) == 3 and parts[1] in ('t', 'T', 'w', 'W'):
            owners.setdefault(canonical(parts[2]), []).append(dict(object=str(rel), byte_identical=same))
pre = Binary(ROOT / 'build/tomokv-PRE', cache, True)
post = Binary(ROOT / 'build/tomokv', cache, True)


def dump_diff(stream, name, left, right):
    stream.write('\nFUNCTION ' + name + '\n')
    for index in range(max(len(left), len(right))):
        a = left[index] if index < len(left) else None
        b = right[index] if index < len(right) else None
        aa = [x + ' | ' + y for x, y in zip(a['ins'], a['encodings'])] if a else []
        bb = [x + ' | ' + y for x, y in zip(b['ins'], b['encodings'])] if b else []
        stream.write(f'CLONE {index} PRE {hex(a["addr"]) if a else "absent"} POST {hex(b["addr"]) if b else "absent"}\n')
        stream.write('\n'.join(difflib.unified_diff(aa, bb, fromfile='PRE', tofile='POST', n=2)) + '\n')


with gzip.open(dest / 'instruction-differences.txt.gz', 'wt') as stream:
    for row in changed:
        origin = owners.get(row['name'], [])
        row['source_objects'] = origin
        if origin and all(item['byte_identical'] for item in origin):
            row['reason'] = ('All defining PRE/POST object files are byte-identical; the linked strict difference '
                             'is relocation/literal-label normalization. The full difference remains reported.')
        dump_diff(stream, row['name'], pre.groups.get(row['name'], []), post.groups.get(row['name'], []))
        stream.write('REASON ' + row['reason'] + '\n')
(dest / 'object-identity.json').write_text(json.dumps(object_rows, indent=2) + '\n')
(dest / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
(dest / 'changed-bodies.md').write_text('# Every changed linked body\n\n' +
    'Strict comparisons retain opcode, register, offsets, immediates and clone multiplicity.\n\n' +
    '| Body | PRE sizes | POST sizes | Reason |\n|---|---|---|---|\n' + ''.join(
        f"| `{row['name']}` | {row['headline_sizes']} | {row['post_sizes']} | {row['reason']} |\n"
        for row in changed))
print('changed', len(changed), flush=True)
