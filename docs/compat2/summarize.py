#!/usr/bin/env python3
"""Summarize final receipts without hiding the retained unsuccessful attempts."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/compat2'


def read(name):
    return json.loads((OUT / name).read_text())


units = read('units-complete/results.json')
tls = read('tls-complete/results.json')
tls_units = read('tls-units-complete/results.json')
selftest = read('selftest-complete/results.json')
expiry = read('expiry-complete/results.json')
directed = read('directed-summary.json')
differ = read('differ-complete/results.json')
assert len(units) == 40 and all(r['returncode'] == 0 for r in units)
assert len(tls) == 25 and all(r['returncode'] == (1 if r['name'] == 'keyupdate-unit' else 0)
                            for r in tls)
assert len(tls_units) == 5 and all(r['returncode'] == 0 for r in tls_units)
assert len(selftest) == 1 and selftest[0]['returncode'] == 0
assert len(expiry) == 20 and all(r['returncode'] == r['expected'] for r in expiry)
assert len(differ) == 4
legs = [json.loads(line) for line in (OUT / 'differ-complete/history/legs.jsonl').read_text().splitlines()]
matrices = []
for result in differ:
    name = result['name']
    log = (OUT / 'differ-complete' / (name + '.log')).read_text()
    history = [r for r in legs if r['run'] == 'compat2-' + name]
    seeds = read(f'differ-complete/{name}/seeds.json')['seeds']
    wanted = {'notify', 'hexpire', 'edgetime', 'hash'}
    focus = [r for r in history if r['suite'] in wanted]
    assert set(seeds) >= {7, 19, 20, 23}
    assert {(r['suite'], r['seed'], r['atomic']) for r in focus} == {
        (suite, seed, atomic) for suite in wanted for seed in seeds for atomic in (0, 1)}
    matrices.append(dict(name=name, returncode=result['returncode'], seeds=seeds,
        recorded_legs=len(history), failed_legs=[r for r in history if r['verdict'] != 'ok'],
        notification_hash_ttl_legs=len(focus),
        tail=log.splitlines()[-6:]))
summary = dict(directed=directed, build_freshness_commands=len(units),
    production_targets=len(read('units-complete/targets.json')), live_tls_checks=len(tls) - 1,
    serverless_tls_cases=len(tls_units), selftest='66/66 plus 14/14 nested',
    differential_matrices=matrices,
    existing_epoll_info_failure=read('infofix-control/summary.json'),
    known_retained_attempts=['one C2 positive-control delivery-order failure; final C2 controls isolate event classes',
                            'one KeyUpdate unit usage error; all five correctly invoked cases pass',
                            'earlier source/harness iterations in intermediate-evidence.tar.xz'],
    arms=read('arm-sha256.json'), identity=read('identity-complete/body-reasons-summary.json'))
(OUT / 'proof-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps({k:v for k,v in summary.items() if k not in ('directed', 'differential_matrices')}, indent=2))
for row in matrices:
    print(row['name'], row['returncode'], row['recorded_legs'], len(row['failed_legs']))
