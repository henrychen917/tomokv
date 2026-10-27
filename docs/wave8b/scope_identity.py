#!/usr/bin/env python3
"""Relate every counted body to its frozen release arm, without relaxing normalization."""
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path

import identity

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 80)))
OUT = ROOT / 'docs/wave8b'
arms = json.loads((OUT / 'arms.json').read_text())
references = {name: arms[key]['path'] for name, key in
              [('headline', 'headline'), ('execindex', 'execindex'), ('pre', 'PRE'), ('post', 'POST')]}
probes = {(arm, namespace): ROOT / 'build/wave8b/commands' / (arm + '-' + namespace) / 'probe'
          for arm in references for namespace in ('normal', 'db0')}
paths = list(dict.fromkeys([*references.values(), *map(str, probes.values())]))
with ProcessPoolExecutor(max_workers=2) as pool:
    inventories = dict(zip(paths, pool.map(identity.inventory, paths)))

rows = []
for (arm, namespace), path in probes.items():
    probe = inventories[str(path)]
    reference = inventories[references[arm]]
    addresses = {(body['address'], name): body for name, bodies in probe['groups'].items() for body in bodies}
    counted = set()
    traces = []
    for trace_path in sorted((OUT / 'instructions').glob(f'{arm}-{namespace}-*.json')):
        trace = json.loads(trace_path.read_text())
        if 'bodies' not in trace:
            continue
        assert trace['binary_sha256'] == probe['sha256'], trace_path
        traces.append(str(trace_path.relative_to(ROOT)))
        counted.update(trace['bodies'])
    assert counted
    bodies = []
    for label in sorted(counted):
        address, name = label.split(' ', 1)
        canonical = identity.audit.canonical(name)
        body = addresses[address, canonical]
        matches = [other['address'] for other in reference['groups'].get(canonical, [])
                   if other['digest'] == body['digest']]
        bodies.append(dict(name=name, address=address, digest=body['digest'],
                           release_matches=matches, equal=bool(matches)))
    rows.append(dict(arm=arm, namespace=namespace, probe=str(path), probe_sha256=probe['sha256'],
                     release=references[arm], release_sha256=reference['sha256'], traces=traces,
                     counted_bodies=len(bodies), matching_bodies=sum(row['equal'] for row in bodies),
                     differences=[row for row in bodies if not row['equal']], bodies=bodies))
result = dict(normalizer='tests/reorder_noop.py, unchanged',
              scope='Every executed named production body in the retained 144 baseline, 48 POST EXEC, and 144 headline/POST main-command traces.',
              rows=rows)
(OUT / 'scope-identity.json').write_text(json.dumps(result, indent=2) + '\n')
for row in rows:
    print(row['arm'], row['namespace'], row['matching_bodies'], '/', row['counted_bodies'], flush=True)
