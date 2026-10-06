#!/usr/bin/env python3
"""Serverless replay of AT15c's recorded requests, replies and timing windows.

This is historical evidence, not a substitute for fresh two-geometry lifetimes.
"""
import contextlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
spec = importlib.util.spec_from_file_location('differ_receipts', ROOT / 'tests/differ.py')
differ = importlib.util.module_from_spec(spec)
sys.argv = ['differ.py', '--list-generators']
with contextlib.redirect_stdout(io.StringIO()):
    try:
        spec.loader.exec_module(differ)
    except SystemExit as stopped:
        assert stopped.code == 0

results = []
for path in sorted((ROOT / 'docs/at15c/receipts').rglob('*.json.gz')):
    trace = json.loads(gzip.decompress(path.read_bytes()))
    if 'operations' not in trace or 'events' not in trace:
        continue
    states = (differ.TtlDeadlines(), differ.TtlDeadlines())
    sends, replies = {}, {}
    checks, positive, failures, absolute_diffs = 0, 0, [], []
    for event in trace['events']:
        side = event['side']
        if event['kind'] == 'send':
            sends[side] = event['before']
            continue
        op = event.get('op')
        if op is None:
            continue
        argv = trace['operations'][op]
        sent = sends[side]
        window = differ.ReplyWindow(sent[1] // differ.NS_PER_MS, event['after'][0] - sent[0])
        reply = bytes.fromhex(event['reply'])
        index = ('target', 'oracle').index(side)
        states[index].observe(argv, reply, window)
        replies.setdefault(op, {})[side] = (reply, window)
        if len(replies[op]) != 2:
            continue
        pair = replies.pop(op)
        target, oracle = pair['target'], pair['oracle']
        name = argv[0].upper()
        if name in ('TTL', 'PTTL', 'HTTL', 'HPTTL'):
            checks += 1
            values = differ.ttl_integers(target[0], name.startswith('H'))
            positive += int(values is not None and any(value >= 0 for value in values))
            with contextlib.redirect_stdout(io.StringIO()) as diagnostic:
                equal = differ.replies_equal(argv, target[0], oracle[0], states,
                                             (target[1], oracle[1]))
            if not equal:
                failures.append(dict(op=op, command=argv, target=target[0].decode(),
                                     oracle=oracle[0].decode(), diagnostic=diagnostic.getvalue()))
        elif name in ('EXPIRETIME', 'PEXPIRETIME', 'HEXPIRETIME', 'HPEXPIRETIME'):
            if target[0] != oracle[0]:
                absolute_diffs.append(dict(op=op, command=argv, target=target[0].decode(),
                                           oracle=oracle[0].decode()))
    results.append(dict(trace=str(path.relative_to(ROOT)), checks=checks, positive=positive,
                        failures=failures, legacy_absolute_diffs=absolute_diffs))

report = dict(traces=len(results), checks=sum(row['checks'] for row in results),
              positive=sum(row['positive'] for row in results),
              failures=sum(len(row['failures']) for row in results),
              legacy_absolute_diffs=sum(len(row['legacy_absolute_diffs']) for row in results),
              results=results)
output = ROOT / 'docs/pttlfix/historical-replay.json'
output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k != 'results'}, indent=2))
for row in results:
    for failure in row['failures']:
        print(row['trace'], failure)
sys.exit(int(report['failures'] != 0))
