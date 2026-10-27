#!/usr/bin/env python3
"""Relate every counted body to its frozen release arm, without relaxing normalization."""
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import subprocess

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
legacy_probes = [ROOT / 'build/wave8b/baseline-probes' / ('headline-' + namespace) / 'probe'
                 for namespace in ('normal', 'db0')]
paths = list(dict.fromkeys([*references.values(), *map(str, probes.values()), *map(str, legacy_probes)]))
with ProcessPoolExecutor(max_workers=2) as pool:
    inventories = dict(zip(paths, pool.map(identity.inventory, paths)))

by_sha = {inventory['sha256']: inventory for inventory in inventories.values()}
rows = []
for (arm, namespace), path in probes.items():
    reference = inventories[references[arm]]
    versions = {}
    for trace_path in sorted((OUT / 'instructions').glob(f'{arm}-{namespace}-*.json')):
        trace = json.loads(trace_path.read_text())
        if 'bodies' not in trace:
            continue
        name = str(trace_path.relative_to(ROOT))
        if 'binary_sha256' in trace:
            digest = trace['binary_sha256']
            assert digest == inventories[str(path)]['sha256'], trace_path
            binding = 'SHA embedded in the trace'
        else:
            original = subprocess.check_output(['git', 'show', 'fe065d3bd:' + name])
            assert trace_path.read_bytes() == original, trace_path
            receipt_name = f'docs/wave8b/instructions/{arm}-{namespace}-build.json'
            original_build = json.loads(subprocess.check_output(['git', 'show', 'fe065d3bd:' + receipt_name]))
            digest = original_build['sha256']
            binding = 'Unchanged trace and full binary SHA from committed baseline fe065d3bd'
        version = versions.setdefault(digest, dict(traces=[], counted=set(), binding=binding))
        version['traces'].append(name)
        version['counted'].update(trace['bodies'])
    for digest, version in versions.items():
        probe = by_sha[digest]
        addresses = {(body['address'], name): body for name, bodies in probe['groups'].items() for body in bodies}
        assert version['counted']
        bodies = []
        for label in sorted(version['counted']):
            address, name = label.split(' ', 1)
            canonical = identity.audit.canonical(name)
            body = addresses[address, canonical]
            matches = [other['address'] for other in reference['groups'].get(canonical, [])
                       if other['digest'] == body['digest']]
            bodies.append(dict(name=name, address=address, digest=body['digest'],
                               release_matches=matches, equal=bool(matches)))
        rows.append(dict(arm=arm, namespace=namespace, probe=probe['path'], probe_sha256=digest,
                         trace_hash_binding=version['binding'],
                         release=references[arm], release_sha256=reference['sha256'], traces=version['traces'],
                         counted_bodies=len(bodies), matching_bodies=sum(row['equal'] for row in bodies),
                         differences=[row for row in bodies if not row['equal']], bodies=bodies))
assert sum(len(row['traces']) for row in rows) == 336
result = dict(normalizer='tests/reorder_noop.py, unchanged',
              scope='Every executed named production body in the retained 144 baseline, 48 POST EXEC, and 144 headline/POST main-command traces.',
              rows=rows)
(OUT / 'scope-identity.json').write_text(json.dumps(result, indent=2) + '\n')
for row in rows:
    print(row['arm'], row['namespace'], row['matching_bodies'], '/', row['counted_bodies'], flush=True)
