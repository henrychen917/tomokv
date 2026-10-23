#!/usr/bin/env python3
"""Verify that instruction traces entered the actual production linked bodies."""
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import identity

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = identity.ROOT
DOC = ROOT / 'docs/wave5/instructions-landing'
BUILD = ROOT / 'build/wave5/commands-landing'
runs = json.loads((DOC / 'runs.json').read_text())
paths = {
    'pre-harness': BUILD / 'pre/probe',
    'post-harness': BUILD / 'post/probe',
    'pre-production': ROOT / 'build/wave5/pre-source/build/tomokv',
    'post-production': ROOT / 'build/tomokv',
    'headline': Path(identity.REFS['headline']),
}
with concurrent.futures.ThreadPoolExecutor(4) as pool:
    inventories = dict(zip(paths, pool.map(identity.inventory, paths.values())))
result = {}
for arm in ('pre', 'post'):
    names = sorted({name for row in runs if row['arm'] == arm for name in row['counts']
                    if name != 'external' and 'CoreConcurrencyTest' not in name})
    demangled = subprocess.check_output(['c++filt', *names], text=True).splitlines()
    rows = []
    for mangled, name in zip(names, demangled):
        # The trace's marker bodies belong to the fixture, not the command.
        if name in ('scope_begin()', 'scope_end()'):
            continue
        harness = inventories[arm + '-harness']['groups'].get(name, [])
        production = inventories[arm + '-production']['groups'].get(name, [])
        same = bool(harness) and identity.signature(harness) == identity.signature(production)
        row = dict(name=name, mangled=mangled, production_equal=same,
                   harness=harness, production=production)
        if arm == 'pre':
            headline = inventories['headline']['groups'].get(name, [])
            row['headline_equal'] = identity.signature(production) == identity.signature(headline)
        rows.append(row)
    result[arm] = rows
result['links'] = {k: {f: v[f] for f in ('path', 'sha256')} for k, v in inventories.items()}
(DOC / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
for arm in ('pre', 'post'):
    failures = [r for r in result[arm] if not r['production_equal'] or not r.get('headline_equal', True)]
    print(arm, len(result[arm]), 'counted production groups;', len(failures), 'differences')
    for row in failures:
        print(row['name'], row['production_equal'], row.get('headline_equal'))
assert all(r['production_equal'] and r.get('headline_equal', True)
           for arm in ('pre', 'post') for r in result[arm])
