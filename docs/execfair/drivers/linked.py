#!/usr/bin/env python3
"""Inventory linked-body differences with the gate's unchanged strict normalizer."""
import difflib
import gzip
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tests'))
import reorder_noop as audit
OUT = ROOT / 'docs/execfair/linked'
OUT.mkdir(exist_ok=True)
SCRATCH = ROOT / 'build/execfair-linked'
SCRATCH.mkdir(exist_ok=True)
pre = audit.Binary(ROOT / 'build/pre/tomokv', SCRATCH, literal_pools=True)
post = audit.Binary(ROOT / 'build/tomokv', SCRATCH, literal_pools=True)
reasons = json.loads((ROOT / 'docs/execfair/identity/changed-bodies-with-reasons.json').read_text())
by_name = {r['name']: r['reason'] for r in reasons}
rows = []
diffs = []
names = sorted(set(pre.groups) | set(post.groups))
for name in names:
    a = sorted(pre.groups.get(name, []), key=lambda b: b['addr'])
    b = sorted(post.groups.get(name, []), key=lambda b: b['addr'])
    equal = [(x['ins'], x['encodings']) for x in a] == [(x['ins'], x['encodings']) for x in b]
    if equal: continue
    row = dict(name=name, pre_sizes=[x['size'] for x in a], post_sizes=[x['size'] for x in b],
               reason=by_name.get(name, 'No direct source edit in this body; inferred compiler/link propagation from the changed EXEC/group and executor templates. Exact differing instructions are retained; this is not an identity pass.'))
    rows.append(row)
    def lines(bodies):
        return [f'clone {i}: {ins} | {enc}\n' for i, body in enumerate(bodies)
                for ins, enc in zip(body['ins'], body['encodings'])]
    diffs.append(dict(name=name, diff=''.join(difflib.unified_diff(lines(a), lines(b), fromfile='PRE', tofile='POST'))))
with gzip.open(SCRATCH / 'changed-diffs.json.gz', 'wt') as stream:
    json.dump(diffs, stream)
(OUT / 'changed-bodies.json').write_text(json.dumps(rows, indent=2)+'\n')
summary = dict(pre_sha256=pre.sha256, post_sha256=post.sha256, total=len(names), changed=len(rows),
               equal=len(names)-len(rows), normalizer='tests/reorder_noop.py Binary(literal_pools=True)',
               strict_diffs=str((SCRATCH / 'changed-diffs.json.gz').relative_to(ROOT)))
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
for path in SCRATCH.glob('*.objdump'): path.unlink()
print(json.dumps(summary, indent=2))
