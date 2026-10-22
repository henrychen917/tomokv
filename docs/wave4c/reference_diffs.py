#!/usr/bin/env python3
"""Explain requested command references without relaxing strict identity."""
import difflib
import gzip
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'docs/wave4'))
import identity

out = ROOT / 'build/wave4c/reference-diffs'
out.mkdir(parents=True, exist_ok=True)
policy = json.loads((ROOT / 'docs/wave4c/reference-policy.json').read_text())
candidate = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'build/wave4c/tomokv-pre'
post = identity.audit.Binary(candidate, out, literal_pools=True)
rows = []
for arm in ('headline', 'moverfix', 'clockcut', 'compat2'):
    before = identity.audit.Binary(identity.REFS[arm], out, literal_pools=True)
    for rule in policy:
        name = rule['name']
        if rule['reference'] != arm and not ('cmd_set_prebuilt<true>' in name and arm == 'compat2'):
            continue
        old = sorted(before.groups.get(name, []), key=lambda b: b['addr'])
        new = sorted(post.groups.get(name, []), key=lambda b: b['addr'])
        lines = lambda bodies: [f'clone {i}: {ins} | {code}' for i, b in enumerate(bodies)
                                for ins, code in zip(b['ins'], b['encodings'])]
        rows.append(dict(name=name, reference=arm,
            reference_sha256=before.sha256, post_sha256=post.sha256,
            reference_sizes=[b['size'] for b in old], post_sizes=[b['size'] for b in new],
            encoded_equal=[b['encodings'] for b in old] == [b['encodings'] for b in new],
            exact_equal=lines(old) == lines(new),
            diff='\n'.join(difflib.unified_diff(lines(old), lines(new), fromfile=arm, tofile='wave4c'))))
    for path in out.glob('*.objdump'):
        path.unlink()
destination = ROOT / 'docs/wave4c' / ('reference-diffs-' + post.sha256[:8] + '.json.gz')
with gzip.open(destination, 'wt') as stream:
    json.dump(rows, stream, indent=2)
print(destination)
