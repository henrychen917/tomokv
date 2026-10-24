#!/usr/bin/env python3
"""Require every counted production group to match its ordinary linked server."""
import concurrent.futures
import json
import os
from pathlib import Path
import identity

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = identity.ROOT
DOC = ROOT / 'docs/wave6/instructions'
BUILD = ROOT / 'build/wave6/commands'
paths = {
    'pre-production': ROOT / 'build/wave6/pre-source/build/tomokv',
    'post-production': ROOT / 'build/tomokv',
    'headline': Path(identity.REFS['headline']),
}
for arm in ('pre', 'post'):
    for ns in ('normal', 'db0'):
        paths[arm + '-' + ns] = BUILD / (arm + '-' + ns) / 'probe'
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    inventories = dict(zip(paths, pool.map(identity.inventory, paths.values())))
result = {}
for arm in ('pre', 'post'):
    runs = json.loads((DOC / ('results-' + arm + '.json')).read_text())
    for ns in ('normal', 'db0'):
        names = sorted({name for row in runs if row['namespace'] == ns
                        for name in row['functions']})
        rows = []
        for name in names:
            harness = inventories[arm + '-' + ns]['groups'].get(name, [])
            production = inventories[arm + '-production']['groups'].get(name, [])
            row = dict(name=name, production_equal=bool(harness) and
                       identity.signature(harness) == identity.signature(production),
                       harness=harness, production=production)
            if arm == 'pre':
                headline = inventories['headline']['groups'].get(name, [])
                row['headline_equal'] = identity.signature(production) == identity.signature(headline)
            rows.append(row)
        result[arm + '-' + ns] = rows
result['links'] = {k: {f: v[f] for f in ('path', 'sha256')} for k, v in inventories.items()}
(DOC / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
failed = []
for arm in ('pre', 'post'):
    for ns in ('normal', 'db0'):
        name = arm + '-' + ns
        failures = [r for r in result[name] if not r['production_equal'] or not r.get('headline_equal', True)]
        print(name, len(result[name]), 'counted groups;', len(failures), 'differences', flush=True)
        failed += failures
for row in failed:
    print(row['name'], row['production_equal'], row.get('headline_equal'), flush=True)
assert not failed
