#!/usr/bin/env python3
"""Run the established finite command scopes against the wave 10 headline.

The owned ptrace child has no server, listener or workload loop. Counts include
executed NOPs in named production bodies, excluding library calls/fixture glue.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import flushfix2_counts as counts

ROOT = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(16))
counts.BUILD = ROOT / 'build/flushfix3/counts'
counts.OUT = ROOT / 'docs/flushfix3/counts'
counts.scope.BUILD = counts.BUILD
counts.scope.OUT = counts.OUT
counts.scope.ARMS = {
    'pre': (ROOT / 'build/flushfix3/pre-source', ROOT / 'build/flushfix3/pre-source/build'),
    'f2': (ROOT, ROOT / 'build'),
    'post': (ROOT, ROOT / 'build'),
}


if __name__ == '__main__':
    # Never let the historical helper silently construct its own older PRE.
    assert (counts.scope.ARMS['pre'][1] / 'tomokv').is_file(), 'build e2b237926 PRE first'
    counts.main()
    files = sorted(counts.OUT.glob('results-*.json'))
    rows = {}
    keys = ('namespace', 'command', 'mode', 'batch', 'atomic', 'threshold')
    for path in files:
        for row in json.loads(path.read_text()):
            rows[row['arm'], *(row[k] for k in keys)] = row
    for arm in ('f2', 'post'):
        comparison = []
        for key, row in rows.items():
            if key[0] != arm or ('pre', *key[1:]) not in rows:
                continue
            pre = rows['pre', *key[1:]]
            comparison.append({k: row[k] for k in keys} | dict(pre=pre['total'],
                post=row['total'], delta=row['total'] - pre['total'],
                pre_probe_sha256=pre['probe_sha256'], post_probe_sha256=row['probe_sha256']))
        if comparison:
            (counts.OUT / f'comparison-{arm}.json').write_text(json.dumps(comparison, indent=2) + '\n')
            print(arm, 'comparisons', len(comparison), 'added', sum(r['delta'] > 0 for r in comparison))
