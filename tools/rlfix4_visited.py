#!/usr/bin/env python3
"""List changes to bodies actually entered by the historical fused GET scopes."""
import json
from pathlib import Path

DOC = Path(__file__).resolve().parents[1] / 'docs/rlfix4'
rows = json.loads((DOC / 'final-counts.json').read_text())
bindings = {}
for arm in ('anchor', 'wave6', 'wave7', 'pre', 'preparse', 'post'):
    for body in json.loads((DOC / f'binding-{arm}.json').read_text())['bodies']:
        bindings[arm, body['namespace'], body['address'], body['name']] = body
visits = {}
for row in rows:
    if row['arm'] not in ('anchor', 'wave6', 'wave7', 'pre', 'post'):
        continue
    if row['command'] != 'GET' or row['mode'] != '1s' or row['route'] not in (
            'local', 'mix', 'parse', 'parsemix', 'r7parse', 'r7mix'):
        continue
    binding_arm = 'preparse' if row['trace_file'].split('/')[-1].startswith('preparse-') else row['arm']
    for identity, count in row['bodies'].items():
        address, name = identity.split(' ', 1)
        body = bindings[binding_arm, row['namespace'], address, name]
        key = row['arm'], row['namespace'], name
        value = visits.setdefault(key, dict(digests=set(), cases=set()))
        # Custom .rlfence retirement assembly is validated instruction by
        # instruction by the binder; it has no STT_FUNC digest.
        value['digests'].update(b['digest'] for b in body.get('probe', []))
        if not body.get('probe'):
            value['digests'].add('custom-section:' + str(body.get('pass_')))
        value['cases'].add((row['batch'], row['route']))
changes = []
for before, after in [('anchor', 'wave6'), ('wave6', 'wave7'), ('wave7', 'pre'), ('pre', 'post')]:
    names = {(ns, name) for arm, ns, name in visits if arm in (before, after)}
    for ns, name in sorted(names):
        a = visits.get((before, ns, name), dict(digests=set(), cases=set()))
        b = visits.get((after, ns, name), dict(digests=set(), cases=set()))
        if a['digests'] != b['digests']:
            changes.append(dict(before=before, after=after, namespace=ns, name=name,
                before_digests=sorted(a['digests']), after_digests=sorted(b['digests']),
                before_cases=sorted(a['cases']), after_cases=sorted(b['cases'])))
(DOC / 'visited-body-transitions.json').write_text(json.dumps(changes, indent=2) + '\n')
print(len(changes), 'changed entered bodies (GET only, fused, ordinary/R7/drain/mix)')
