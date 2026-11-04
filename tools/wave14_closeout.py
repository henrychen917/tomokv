#!/usr/bin/env python3
"""Bind completed wave14 controls without replacing any original verdict."""
import json
import os
from pathlib import Path
import re

from wave14 import DOC, ROOT, save, sha


def receipt(tag):
    path = DOC / 'jobs' / (tag + '.json')
    value = json.loads(path.read_text())
    assert sha(Path(value['archive'])) == value['archive_sha256']
    return path, value


def fifo():
    plans = [
        ('merged-final-uring', 'Merged, four client CPUs per slot'),
        ('fifo-final-eight-client-cpus', 'Merged, eight client CPUs overlapping other correctness work'),
        ('fifo-lane-four-client-cpus-isolated', 'Isolated execfifo3, four client CPUs'),
        ('fifo-final-eight-client-cpus-isolated', 'Isolated merged, eight client CPUs'),
        ('merged-final-epoll', 'Merged epoll sweep, eight client CPUs'),
    ]
    runs = []
    for tag, allocation in plans:
        path, rec = receipt(tag)
        root = Path(rec['run_directory']) / 'jobs/txnorder_fifo_live'
        legs = []
        for item in sorted(root.glob('fifo-*.json')):
            d = json.loads(item.read_text())
            n = d['exec_clients']
            share = sum(d['completions'][n:]) / sum(d['completions'][:n])
            errors = re.findall(r'^AssertionError: (.+)$', item.with_suffix('.log').read_text(), re.M)
            windows = d['windows']
            assert len(windows) == d['seconds'] == 60
            assert all(len(w['completions']) == n + 4 == 68 for w in windows)
            progress = min(min(w['completions']) for w in windows)
            assert progress > 0 and d['actual'] == d['expected']
            assert d['deltas']['atomic_txn_order_violations'] == 0
            assert d['deltas']['atomic_txn_fifo_waits'] > 0
            legs.append(dict(leg=item.stem, source=str(item.relative_to(ROOT)),
                sha256=sha(item), log_sha256=sha(item.with_suffix('.log')),
                windows=len(windows), clients=n + 4, minimum_window_progress=progress,
                exact_final_values=True, order_violations=0,
                fifo_waits=d['deltas']['atomic_txn_fifo_waits'], share=share,
                share_lower=(4 / n) / 2, share_upper=(4 / n) * 2,
                passed=d.get('pass', False), failures=errors,
                latency_assertions_reached='fifo' in d, latency=d.get('fifo')))
        assert len(legs) == 16
        runs.append(dict(tag=tag, allocation=allocation, receipt_sha256=sha(path),
            binary_sha256=rec['binary_sha256'],
            passed=sum(x['passed'] for x in legs), failed=sum(not x['passed'] for x in legs),
            legs=legs))
    assert [(r['passed'], r['failed']) for r in runs] == [(8, 8), (9, 7), (8, 8), (16, 0), (16, 0)]
    save(DOC / 'fifo-allocation-audit.json', dict(runs=runs,
        interpretation='Four-client-CPU share failures also occur on isolated execfifo3. '
        'Two merged eight-client-CPU jobs pass every unchanged bound. The overlapping '
        'eight-client-CPU attempt remains failed; these controls neither relabel its '
        'latency failures nor certify performance merit. Share failures did not reach '
        'later latency assertions. No fairness bound or production predicate changed.'))


def blockfix4():
    tags = ['merged-final-uring', 'merged-final-blockfix4-epoll-db1',
            'merged-final-blockfix4-uring-db16', 'merged-final-blockfix4-epoll-db16']
    runs = []
    for tag in tags:
        path, rec = receipt(tag)
        root = Path(rec['run_directory']) / 'jobs/blockfix4'
        cases = []
        for name in ['scripts', 'moves', 'creators', 'removed', 'mpop']:
            result_path = root / name / 'results.json'
            rows = json.loads(result_path.read_text())
            witness_path = root / name / 'witness.json'
            witness = json.loads(witness_path.read_text())
            assert witness['binary_sha256'] == rec['binary_sha256']
            assert all(row['passed'] and not row['errors'] for row in rows)
            cases.append(dict(case=name, results_sha256=sha(result_path),
                witness_sha256=sha(witness_path), engine=witness['engine'],
                databases=witness['databases'], legs=len(rows), all_passed=True))
        creator_rows = json.loads((root / 'creators/results.json').read_text())
        restore = []
        for row in creator_rows:
            r = row['summary']['results']['RESTORE-stream']
            assert r['attempts'] == r['parked'] == r['hits'] == r['served'] == 2
            assert r['defects'] == r['served_after_long'] == r['served_after_plain_push'] == 0
            assert not r['creator_errors']
            restore.append(dict(label=row['label'], **r))
        assert len(restore) == 17
        runs.append(dict(tag=tag, receipt_sha256=sha(path),
            binary_sha256=rec['binary_sha256'], cases=cases, restore_stream=restore))
    candidate = [x for r in runs for x in r['restore_stream'] if x['label'].startswith('tomokv-')]
    oracle = [x for r in runs for x in r['restore_stream'] if x['label'].startswith('redis-')]
    assert len(candidate) == 64 and len(oracle) == 4
    save(DOC / 'blockfix4-final-matrix.json', dict(runs=runs,
        restore_stream=dict(candidate_geometries=len(candidate),
            candidate_parked_and_served=sum(x['hits'] for x in candidate),
            oracle_geometries=len(oracle), oracle_parked_and_served=sum(x['hits'] for x in oracle)),
        note='All five unchanged public case collectors complete on both engines and both '
             'namespace builds. RESTORE-stream is included in the existing creator row; '
             '128 means candidate armed wake attempts, not 128 distinct geometries.'))


def txnorder():
    runs = []
    for i in range(1, 4):
        tag = f'txnorder-aof-capture-{i}'
        path, rec = receipt(tag)
        native_path = DOC / (tag + '-native.json')
        native = json.loads(native_path.read_text())
        assert sha(Path(native['native'])) == native['native_sha256']
        root = Path(rec['run_directory']) / 'jobs/txnorder-fused-0'
        output = root / 'txnorder-2s-0.txt'
        text = output.read_text()
        markers = re.findall(r'^PASS (\S+)$', text, re.M)
        assert set(markers) == {'a', 'b', 'c', 'armed', 'd', 'txnorder_f1', 'txnorder_f2',
            'txnorder_f4', 'txnorder_f5', 'txnorder_f6', 'txnorder_f8', 'txnorder_claims',
            'txnorder_placement', 'txnorder_readonly'}
        summaries = [json.loads(line) for line in text.splitlines() if line.startswith('{')]
        replay = next(x for x in summaries if x.get('row') == 'd-reload')
        assert replay['exact'] is True and replay['keys'] == 2
        assert rec['exit_code'] == 0 and (root / 'done').read_text().split() == ['0', '1', '0']
        captures = list(root.glob('txnorder-failure-*'))
        assert not captures
        start = json.loads((DOC / 'jobs' / (tag + '-started.json')).read_text())
        command = start['command']
        allocation = {k: command[command.index('--' + k) + 1]
                      for k in ('server-cores', 'load-cores', 'ports')}
        runs.append(dict(tag=tag, receipt_sha256=sha(path),
            native_sha256=native['native_sha256'], launcher_sha256=native['launcher_sha256'],
            native_receipt_sha256=sha(native_path), allocation=allocation,
            output_sha256=sha(output), passed_markers=markers, replay=replay,
            failure_captures=0, exit_code=rec['exit_code']))
    original = DOC / 'txnorder-aof-original-failure.json'
    save(DOC / 'txnorder-aof-diagnostics.json', dict(original=str(original.relative_to(ROOT)),
        original_sha256=sha(original), runs=runs,
        conclusion='Original fused atomic-0 epoll AOF TimeoutError and 30-second shutdown '
        'hang remain unexplained and unresolved. Three complete fresh gate-job reruns '
        'pass all assertions and exact AOF replay, with unchanged native production bytes. '
        'The failure-only observer never fired, so no server backtrace was captured. '
        'A separate same-user ptrace control verifies the diagnostic mechanism. '
        'Passing reruns do not replace the original failure or establish a fix.'))


if __name__ == '__main__':
    assert os.sched_getaffinity(0) <= set(range(32))
    fifo()
    blockfix4()
    txnorder()
    print('Bound all FIFO allocations, blockfix4 matrices, and AOF diagnostic attempts.')
