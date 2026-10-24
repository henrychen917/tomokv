#!/usr/bin/env python3
"""Retain strict instruction diffs for every final linked hot-body mismatch."""
import difflib
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
out = ROOT / 'build/dispatchfix-hot-diff'
out.mkdir(exist_ok=True)
pre = audit.Binary(ROOT / 'build/tomokv-PRE', out, literal_pools=True)
post = audit.Binary(ROOT / 'build/tomokv', out, literal_pools=True)
summary = json.loads((ROOT / 'docs/dispatchfix/identity/summary.json').read_text())
rows = []
for row in summary['changed_hot']:
    name = row['name']
    a = sorted(pre.groups.get(name, []), key=lambda x:x['addr'])
    b = sorted(post.groups.get(name, []), key=lambda x:x['addr'])
    before = [line for clone in a for line in clone['ins']]
    after = [line for clone in b for line in clone['ins']]
    equal = [x['encodings'] for x in a] == [x['encodings'] for x in b]
    rows.append(dict(name=name, encodings_equal=equal,
                     pre_sizes=[x['size'] for x in a], post_sizes=[x['size'] for x in b],
                     diff=list(difflib.unified_diff(before,after,fromfile='PRE',tofile='POST'))))
path = ROOT / 'docs/dispatchfix/identity'
(path / 'hot-linked-diffs-all.json').write_text(json.dumps(rows,indent=2)+'\n')
constant_rows = [r for r in rows if 'prepare_local_read' in r['name'] or '::on_cqe<' in r['name']]
assert len(constant_rows) == 6
(path / 'hot-linked-diffs.json').write_text(json.dumps(constant_rows,indent=2)+'\n')
print(len(rows), 'hot differences;', len(constant_rows), 'constant/table candidates')
for f in out.glob('*.objdump'): f.unlink()
