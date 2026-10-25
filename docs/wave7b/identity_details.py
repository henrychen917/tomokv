#!/usr/bin/env python3
"""Retain exact diffs for changed command-counted helpers using verified equivalent PRE bodies."""
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('wave7_identity', ROOT / 'docs/wave7/identity.py')
audit = importlib.util.module_from_spec(spec); spec.loader.exec_module(audit)
out = ROOT / 'build/wave7b/identity-details'; out.mkdir(exist_ok=True)
report = json.loads((ROOT / 'docs/wave7b/identity.json').read_text())
pre = audit.audit.Binary(ROOT / 'build/tomokv-wave7-before-prebuiltfix', out, literal_pools=True)
post = audit.audit.Binary(ROOT / 'build/tomokv', out, literal_pools=True)
lines = []
for name in report['counted_command_changed']:
    row = next(r for r in report['changed'] if r['name'] == name)
    a, b = pre.groups[name], post.groups[name]
    def digest(body):
        return hashlib.sha256(json.dumps([body['ins'], body['encodings']]).encode()).hexdigest()
    assert [digest(x) for x in a] == [x['digest'] for x in row['before']], name
    assert [digest(x) for x in b] == [x['digest'] for x in row['after']], name
    lines.append(name + '\n')
    for x, y in zip(a,b):
        lines.extend(z+'\n' for z in difflib.unified_diff(
            [i+' | '+e for i,e in zip(x['ins'],x['encodings'])],
            [i+' | '+e for i,e in zip(y['ins'],y['encodings'])],
            fromfile='verified wave7 body', tofile='wave7b', lineterm=''))
(ROOT / 'docs/wave7b/counted-body-diffs.txt').write_text(''.join(lines))
for p in out.glob('*.objdump'): p.unlink()
