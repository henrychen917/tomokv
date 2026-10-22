#!/usr/bin/env python3
"""Offline linked-body check of the lowest restoring budget tested."""
import json
from pathlib import Path
import sys
sys.path.insert(0, 'tests')
sys.path.insert(0, 'tools')
import reorder_noop as audit
import r7shadow_noop
from lbstall_artifacts import HOT

out = Path('build/moverfix2/restore-linked')
out.mkdir(parents=True, exist_ok=True)
a = audit.Binary('build/tomokv', out, literal_pools=True)
b = audit.Binary('build/moverfix2/trials/normal-136000-tomokv', out, literal_pools=True)
for binary in (a, b):
    r7shadow_noop.off_roles(binary)
rows = []
for name in sorted(a.groups.keys() | b.groups.keys()):
    if not (HOT.search(name) or audit.category(name)):
        continue
    before, after = a.groups.get(name, []), b.groups.get(name, [])
    def content(bodies):
        return [(f['size'], f['ins'], f['encodings'], f['aliases']) for f in bodies]
    equal = content(before) == content(after)
    rows.append(dict(name=name, equal=equal, hot=bool(HOT.search(name)),
                     category=audit.category(name), before_sizes=[f['size'] for f in before],
                     trial_sizes=[f['size'] for f in after]))
counts = lambda binary: {ns: sum(len(bodies) for name, bodies in binary.groups.items()
                                if audit.category(name) and
                                ('tomo_db0' if 'tomo_db0::' in name else 'tomo') == ns)
                         for ns in ('tomo', 'tomo_db0')}
report = dict(post_sha256=a.sha256, trial_sha256=b.sha256,
              post_inventory=counts(a), trial_inventory=counts(b),
              selected=len(rows), changed=sum(not r['equal'] for r in rows),
              hot=sum(r['hot'] for r in rows),
              hot_changed=sum(r['hot'] and not r['equal'] for r in rows),
              changed_bodies=[r for r in rows if not r['equal']])
Path('docs/moverfix2/restore-linked.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k:v for k,v in report.items() if k != 'changed_bodies'}, indent=2))
