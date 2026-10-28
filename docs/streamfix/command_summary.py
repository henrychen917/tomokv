#!/usr/bin/env python3
"""Check the complete serverless matrix without dropping external-call evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/streamfix/instructions'
keys = ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold')
pre = json.loads((DOC / 'results-pre.json').read_text())
post = json.loads((DOC / 'results-post.json').read_text())


def excluded(row):
    result = {}
    suffix = ' in section .text of ' + str(ROOT / 'build/streamfix/commands' /
                                           (row['arm'] + '-' + row['namespace']) / 'probe')
    for name, count in row['excluded'].items():
        if name.endswith(suffix):
            # This is the fixture's completion callback, already outside scope.
            # Normalize only its known artifact pathname; keep its exact symbol
            # and count, and leave every external-library target untouched.
            assert '::CoreConcurrencyTest::run<' in name and '::_FUN(' in name
            name = name.removesuffix(suffix)
        assert name not in result
        result[name] = count
    return result


pairs = []
for row in post:
    old, = [r for r in pre if all(r[k] == row[k] for k in keys)]
    assert excluded(old) == excluded(row)
    pairs.append({k: row[k] for k in keys} | dict(
        pre=old['total'], post=row['total'], delta=row['total'] - old['total'],
        pre_per_command=old['total'] / row['batch'], post_per_command=row['total'] / row['batch'],
        functions_equal=old['functions'] == row['functions'], external_calls_equal=True))
assert len(pairs) == 72
single = [r for r in pairs if r['command'] in ('GET', 'SET', 'INCR')]
scatter = [r for r in pairs if r['command'] in ('MGET', 'MSET')]
assert len(single) == 48 and all(r['delta'] == 0 and r['functions_equal'] for r in single)
assert len(scatter) == 24 and all(r['delta'] == 0 and r['functions_equal'] for r in scatter)
(DOC / 'comparison.json').write_text(json.dumps(pairs, indent=2) + '\n')
summary = dict(post_sha256=hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest(),
               comparisons=72, single_key_zero_added=48, scatter_totals_and_functions_equal=24,
               external_library_and_fixture_callback_counts_equal=72,
               normalization='Only the known fixture callback artifact pathname; raw target names remain in every trace.')
(DOC / 'counts-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
print(json.dumps(summary))
