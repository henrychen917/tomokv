#!/usr/bin/env python3
"""Audit archived gate receipts without starting a server or changing a test."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/notifyorder'
runs = json.loads((DOC / 'proof/inventory.json').read_text())
by_name = {run['log']: run for run in runs}
order = 'keyspace lazy-expiry order vs Redis 7.4'
aof = 'local script notification AOF vs Redis 7.4'
abba = 'ABBA comparison + saturation negative controls'
unit = 'netcmd notify-oom regression'
expected_failures = {
    'gate-verified-pre.log': {order, aof},
    'gate-verified-pad-a.log': {order},
    'gate-verified-no-salvage.log': {order},
    'gate-broad-post.log': {abba},
    'gate-broad-pre.log': {abba},
    'gate-unit-pre-new-assertions.log': {unit},
    'gate-unit-no-salvage-final.log': {unit},
    'gate-callback-before.log': {'flushfix flush witnesses'},
    'gate-abba-fenced.log': {abba},
}
summary = []
for run in runs:
    path = ROOT / run['archive']
    assert hashlib.sha256(path.read_bytes()).hexdigest() == run['archive_sha256'], path
    rows = Counter((row['status'], row['label']) for row in run['rows'])
    public = Counter((row['status'], row['label']) for row in run['public_rows'])
    assert rows == public, (run['log'], rows-public, public-rows)
    for done in run['completions']:
        rc, passed, failed = map(int, done['record'].split())
        assert rc == 0, (run['log'], 'nonzero job finalization', done)
        observed = Counter(row['status'] for row in run['rows'] if row['job'] == done['job'])
        assert observed['ok'] == passed and observed['FAIL'] == failed, (run['log'], done, observed)
    failed_labels = {row['label'] for row in run['rows'] if row['status'] != 'ok'}
    if run['stage'] != 'superseded implementation regression receipt':
        assert failed_labels == expected_failures.get(run['log'], set()), (run['log'], failed_labels)
    summary.append(dict(log=run['log'], run=run['run'], stage=run['stage'],
                        jobs=len(run['completions']), rows=dict(Counter(r['status'] for r in run['rows'])),
                        failures=sorted(failed_labels)))

for arm in ('post', 'pre'):
    run = by_name[f'gate-broad-{arm}.log']
    requested = set((DOC / 'correctness-jobs.txt').read_text().split())
    completed = {entry['job'] for entry in run['completions']}
    assert requested <= completed and len(completed) == 145, (arm, requested-completed)

for arm in ('post', 'pre', 'pad-a', 'no-salvage'):
    run = by_name[f'gate-verified-{arm}.log']
    legs = [leg for leg in run['legs'] if leg['job'] == 'notify_order']
    expected = {f'order-{mode}-{engine}-a{atomic}-rl{rl}.log'
                for mode, reads in (('1s', (0, 1)), ('2s', (0,)))
                for engine in ('epoll', 'uring') for atomic in (0, 1) for rl in reads}
    assert len(legs) == 12 and {leg['leg'] for leg in legs} == expected, arm
    if arm == 'post':
        assert all(leg['score'] == [23, 0] for leg in legs)
    if arm in ('pre', 'pad-a'):
        assert all(leg['c2_failures'] == 2 and leg['c7_failures'] == 0 for leg in legs)
    if arm == 'no-salvage':
        assert all(leg['c7_failures'] == int('-a1-' in leg['leg']) and
                   len(leg['failures']) == leg['c7_failures'] for leg in legs)
    aof_legs = [leg for leg in run['legs'] if leg['job'] == 'notify_aof']
    assert len(aof_legs) == (0 if arm == 'no-salvage' else 8), arm
    assert all(leg['aof_pass'] == (arm != 'pre') for leg in aof_legs), arm

differential = []
for arm in ('post', 'pre'):
    for engine in ('uring', 'epoll'):
        run = by_name[f'differ-{arm}-{engine}.log']
        parts = run['differential']['parts']
        wanted = {'differ-split-0': 235, 'differ-split-1': 239,
                  'differ-armed-0': 230, 'differ-armed-1': 234, 'differ-equivalence': 0}
        assert {part['job']: part['comparisons'] for part in parts} == wanted
        assert all(not part['failed_comparisons'] for part in parts)
        assert all(part['complete']['complete'] for part in parts)
        assert sum(part['repeated_multi'] for part in parts) == 8
        cells = [cell for part in parts for cell in part['equivalence']]
        assert len(cells) == 1 and cells[0]['completed_cells'] == 16 and cells[0]['verdicts'] == {'ok': 16}
        boots, placement = Counter(), set()
        for log in (ROOT / run['run']).glob('jobs/differ-*/differ/**/*.log'):
            for line in log.read_text(errors='replace').splitlines():
                if line.startswith('tomokv-cpp:'):
                    boots['epoll' if ', epoll,' in line else 'uring' if ', io_uring,' in line else line] += 1
                if line.strip().startswith('domain  0:'):
                    placement.add(line.strip())
        assert boots == {engine: 36}, (arm, engine, boots)
        assert placement == {'domain  0: 8 cpus [96,97,98,99,100,101,102,103]'}, placement
        differential.append(dict(arm=arm, engine=engine, comparisons=938, equivalence_cells=16,
                                 multi_repeats=8, actual_boot_engines=dict(boots), placement=sorted(placement)))

status = (DOC / 'final-unit-status.log').read_text()
assert 'INVALID' not in status, status
entries = [line.rsplit(' rc=', 1) for line in status.splitlines()]
expected_status = {'unit post': '0', 'unit no-salvage-final': '1',
                   'unit pre-new-assertions': '1', 'unit pre': '0',
                   'callback before': '1', 'callback pre': '0',
                   'atomic correctness post': '0', 'fenced abba': '1',
                   'gates_test': '0', 'freshness': '0'}
expected_status.update({entry: '0' for entry in (
    'abba_instrument.py --self-test', 'background_environment_test.py',
    'gate_history.py self-test', 'gate_process_test.py', 'gate_subset_test.py',
    'wb_policy.py --self-test', 'lb_stationary.py --self-test',
    'netio.py --self-test', 'gateprod.py --self-test', 'tailgen_stall.py --self-test')})
assert len(entries) == len(expected_status) and dict(entries) == expected_status, status
for name, digest in json.loads((DOC / 'tested-source.json').read_text())['files'].items():
    assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, name
for name in ('pre', 'post'):
    run = by_name['gate-broad-pre.log' if name == 'pre' else 'gate-atomic-correctness-post.log']
    directory = ROOT / run['run'] / 'jobs/atomic_batteries'
    texts = [p.read_text(errors='replace') for p in directory.glob('*.txt')]
    assert any('SKIP' in text and 'rate' in text.lower() for text in texts), (name, 'missing rate exclusion')
    assert all('pipe=' not in text for text in texts), (name, 'unexpected rate result')

result = dict(runs=summary, differential=differential,
              comparisons=3752, equivalence_cells=64, unexpected_failures=[],
              note='Intentional PRE/negative controls and immutable EXPECT guard remain red; no full-gate receipt.')
(DOC / 'proof-audit.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))
