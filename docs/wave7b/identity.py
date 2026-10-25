#!/usr/bin/env python3
"""Compare wave7b linked bodies against the supplied wave-7 HEAD inventory."""
import gzip
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('wave7_identity', ROOT / 'docs/wave7/identity.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
before_sha = '02e1a1a2cd0925d6dfa8deb3510febd0df745badbb03c95d2d8e41683f51c753'
with gzip.open(audit.OUT / before_sha / 'inventory.json.gz', 'rt') as stream:
    before = json.load(stream)
after = audit.inventory(ROOT / 'build/tomokv')
rows = []
for name in sorted(set(before['groups']) | set(after['groups'])):
    pre, post = before['groups'].get(name, []), after['groups'].get(name, [])
    if audit.signature(pre) != audit.signature(post):
        rows.append(dict(name=name, before=pre, after=post))
result = dict(before_sha256=before_sha, after_sha256=after['sha256'],
              before_groups=len(before['groups']), after_groups=len(after['groups']),
              changed_groups=len(rows), changed=rows)
counted = set()
for arm in ('pre', 'post'):
    for row in json.loads((ROOT / 'docs/wave7/instructions' / ('results-' + arm + '.json')).read_text()):
        counted.update(audit.audit.canonical(name) for name in row['functions'])
result['counted_command_groups'] = len(counted)
result['counted_command_changed'] = [row['name'] for row in rows if row['name'] in counted]
result['main_command_changed'] = [row['name'] for row in rows if audit.HOT.search(row['name'])]
(ROOT / 'docs/wave7b/identity.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k:v for k,v in result.items() if k != 'changed'}))
for row in rows:
    print(row['name'])
