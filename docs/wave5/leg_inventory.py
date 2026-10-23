#!/usr/bin/env python3
"""Check declared lane matrices against the archived final gate witnesses."""
import itertools
import json
import os
from pathlib import Path
import re
import tarfile

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
DOC = Path(__file__).resolve().parent
sha = json.loads((DOC / 'gate/correctness-landing/result.json').read_text())['binary_sha256']
proof = {}
with tarfile.open(DOC / 'gate/correctness-landing/witnesses.tar.gz') as tar:
    def read(job, name):
        with tar.extractfile('0/jobs/' + job + '/' + name) as stream:
            text = stream.read().decode()
        assert text.strip(), (job, name)
        return text

    def logs(group, job, names):
        names = list(names)
        for name in names:
            read(job, name)
        proof[group] = dict(job=job, log_count=len(names), logs=names)

    logs('bugs5', 'bugs5', (
        f'{case}{control}-{mode}-{engine}-{atomic}.log'
        for case, control, mode, engine, atomic in itertools.product(
            ('scancompact', 'slowlog_identity', 'read_local_lfu'), ('', '-control'),
            ('1s', '2s'), ('epoll', 'uring'), (0, 1))))
    logs('compat3', 'compat3', (
        f'{case}-db{db}-{mode}-{engine}-a{atomic}-rl{rl}.log'
        for case, db, (mode, rl), engine, atomic in itertools.product(
            ('pubsub', 'pending', 'history', 'grammar', 'glob', 'flags'), (1, 16),
            (('1s', 0), ('1s', 1), ('2s', 0)), ('epoll', 'uring'), (0, 1))))
    for job in ('trackfix_order', 'trackfix_accounting'):
        logs(job, job, (f'order-{mode}-{engine}-a{atomic}-rl{rl}.log'
                       for mode, engine, atomic, rl in itertools.product(
                           ('1s', '2s'), ('epoll', 'uring'), (0, 1), (0, 1))))
    for feature in ('deferred', 'hz', 'sleep', 'signal'):
        logs('iofix-' + feature, 'iofix-' + feature,
             (f'{feature}-{mode}-{engine}.log'
              for mode, engine in itertools.product(('1s', '2s'), ('epoll', 'uring'))))
    logs('txnorder2', 'txnorder2', [f'R{i}.log' for i in range(1, 13)] + ['rename.log'] +
         [f'{case}-{mode}-{engine}-{db}.log'
          for case, mode, engine, db in itertools.product(
              ('serve', 'flush', 'readonly'), ('1s', '2s'), ('epoll', 'uring'), (1, 16))])
    logs('txnorder_wake', 'txnorder_wake', ['wake.log'])
    results = []
    for direction, outcome, engine, atomic in itertools.product(
            ('io-ex', 'ex-io'), ('complete', 'rollback'), ('epoll', 'uring'), (0, 1)):
        name = f'fliplisten-{direction}-{outcome}/{engine}-a{atomic}/result.json'
        row = json.loads(read('fliplisten', name))
        assert row['sha256'] == sha and not row['errors'], row
        assert row['arrived'] > 0 and row['served'] == row['arrived'], row
        results.append(dict(path=name, arrived=row['arrived'], served=row['served']))
    proof['fliplisten'] = results
    for feature in ('query_stats', 'unix', 'config', 'tls', 'idle_buffers'):
        job = 'netfix_' + feature
        result = json.loads(read(job, 'proof/results.json'))
        if feature == 'tls':
            expected = {'oracle-oracle'} | {f'{m}-{e}' for m, e in itertools.product(('1s', '2s'), ('epoll', 'uring'))}
        elif feature == 'unix':
            kinds = ('regular', 'stale', 'live', 'symlink')
            expected = {f'oracle-oracle-{k}' for k in kinds} | {
                f'{m}-{e}-{k}' for m, e, k in itertools.product(('1s', '2s'), ('epoll', 'uring'), kinds)}
        else:
            expected = {'oracle-oracle-tcp', 'oracle-oracle-tls'} | {
                f'{m}-{e}-{t}' for m, e, t in itertools.product(('1s', '2s'), ('epoll', 'uring'), ('tcp', 'tls'))}
        assert set(result) == expected, (job, set(result) ^ expected)
        proof[job] = sorted(result)
    r7 = read('reorder_identity', 'receipt.log')
    assert 'strict_noop=True: 305/305 identical bodies' in r7
    assert 'PASS missing policy symbol, missing split-local parser, missing fliplisten clone and changed opcode' in r7
    proof['r7'] = r7.strip().splitlines()

for engine in ('uring', 'epoll'):
    climon = {}
    with tarfile.open(DOC / f'gate/differ-{engine}/witnesses.tar.gz') as tar:
        for geometry, atomic in itertools.product(('split', 'armed'), (0, 1)):
            name = f'differ-{geometry}-{atomic}'
            with tar.extractfile(f'0/jobs/{name}/output.log') as stream:
                text = stream.read().decode()
            lines = [line.strip() for line in text.splitlines() if 'differ climon (' in line]
            assert len(lines) == 5 and all('0 diffs -> PASS' in line for line in lines), lines
            seeds = {int(re.search(r'seed=(\d+)', line)[1]) for line in lines}
            assert {7, 19, 20, 23} <= seeds, seeds
            climon[name] = lines
    proof['differ-' + engine] = climon
(DOC / 'leg-inventory.json').write_text(json.dumps(dict(binary_sha256=sha, evidence=proof), indent=2) + '\n')
print('PASS all declared lane matrices, 305 R7 bodies/four controls, and 40 climon seed legs')
