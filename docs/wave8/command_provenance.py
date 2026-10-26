#!/usr/bin/env python3
"""Require every counted production group to match its ordinary linked server."""
import concurrent.futures
import json
import gzip
import constant_provenance
import os
from pathlib import Path
import identity
import switch_provenance

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = identity.ROOT
DOC = ROOT / 'docs/wave8/instructions'
BUILD = ROOT / 'build/wave8/commands'
paths = {
    'pre-production': ROOT / 'build/wave8/pre-source/build/tomokv',
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
        selected = [row for row in runs if row['namespace'] == ns]
        assert all('bodies' in row for row in selected), 'trace actual body addresses first'
        names = sorted({name for row in selected for name in row['bodies']})
        rows = []
        for counted in names:
            address, name = counted.split(' ', 1)
            harness = [body for body in inventories[arm + '-' + ns]['groups'].get(name, [])
                       if body['address'] == address]
            assert len(harness) == 1, (counted, harness)
            production = inventories[arm + '-production']['groups'].get(name, [])
            # The fixture can emit an additional private helper clone. Compare
            # the exact body entered by the trace, never an unexecuted namesake.
            row = dict(name=name, address=address,
                       production_equal=harness[0]['digest'] in identity.signature(production),
                       harness=harness, production=production)
            if arm == 'pre':
                headline = inventories['headline']['groups'].get(name, [])
                row['headline_equal'] = harness[0]['digest'] in identity.signature(headline)
            rows.append(row)
        result[arm + '-' + ns] = rows
result['links'] = {k: {f: v[f] for f in ('path', 'sha256')} for k, v in inventories.items()}
(DOC / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
if os.getenv('WAVE8_PROVENANCE_INVENTORY_ONLY') == '1':
    raise SystemExit(0)
switch_names = {
    row['name'] for arm in ('pre', 'post') for ns in ('normal', 'db0')
    for row in result[arm + '-' + ns] if not row['production_equal']
}
constant_names={n for n in switch_names if '::kvobj_' not in n}
switch_names-=constant_names
constant_proofs={}
if constant_names:
    raw=json.load(gzip.open(DOC/'provenance-bodies.json.gz','rt'))
    for arm in ('pre','post'):
        for ns in ('normal','db0'):
            key=arm+'-'+ns
            for row in result[key]:
                name=row['name']
                if row['production_equal'] or name not in constant_names:continue
                harness=next(b for b in raw[key][name] if hex(b['addr'])==row['address'])
                production=raw[arm+'-production'][name]
                assert len(production)==1
                production=production[0]
                assert constant_provenance.signature(harness)==row['harness'][0]['digest']
                assert constant_provenance.signature(production)==row['production'][0]['digest']
                proof=constant_provenance.prove(paths[arm+'-production'],production,paths[key],harness)
                constant_proofs[key+' '+name]=proof
                row['verified_constant_equal']=True
                if arm=='pre':
                    row['verified_constant_headline_equal']=row['production'][0]['digest'] in identity.signature(inventories['headline']['groups'][name])
    (DOC/'constant-provenance.json').write_text(json.dumps(constant_proofs,indent=2)+'\n')
switches = {}
if switch_names:
    assert switch_names == {
        'tomo_db0::kvobj_external_bytes(tomo_db0::KvObj const*)',
        'tomo_db0::kvobj_free_with_capacity(tomo_db0::KvObj*, unsigned long)',
    }, switch_names
    selected = ['pre-db0', 'post-db0', 'pre-production', 'post-production', 'headline']
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        switches = dict(zip(selected, pool.map(
            lambda key: switch_provenance.inspect(paths[key], switch_names), selected)))
    for arm in ('pre', 'post'):
        for row in result[arm + '-db0']:
            if row['name'] not in switch_names:
                continue
            name = row['name']
            probe = switches[arm + '-db0'][name]
            production = switches[arm + '-production'][name]
            row['verified_switch_equal'] = probe == production
            if arm == 'pre':
                row['verified_switch_headline_equal'] = probe == switches['headline'][name]
    (DOC / 'switch-provenance.json').write_text(json.dumps(
        dict(binaries=switches), indent=2) + '\n')
(DOC / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
failed = []
for arm in ('pre', 'post'):
    for ns in ('normal', 'db0'):
        name = arm + '-' + ns
        failures = [r for r in result[name]
                    if not (r['production_equal'] or r.get('verified_switch_equal', False) or r.get('verified_constant_equal',False))
                    or not (r.get('headline_equal', True) or r.get('verified_switch_headline_equal', False) or r.get('verified_constant_headline_equal',False))]
        print(name, len(result[name]), 'counted groups;', len(failures), 'differences', flush=True)
        failed += failures
for row in failed:
    print(row['name'], row['production_equal'], row.get('headline_equal'), flush=True)
assert not failed
