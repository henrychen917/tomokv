#!/usr/bin/env python3
"""Compare tests/redis_tcl.py survey summaries (no manifest) between PRE and POST.

Usage: cfgfix2_tcl_compare.py OUT.json PRE-1s PRE-2s POST-1s POST-2s
Each argument is a redis_tcl.py --output directory holding summary.json. A test is
"gained" when POST passes it in both modes and PRE fails it in at least one mode.
"""
import json
from pathlib import Path
import sys


def statuses(folder):
    report = json.loads((Path(folder) / 'summary.json').read_text())
    result = {}
    for row in report['rows']:
        for event in row['events']:
            name = event['test']
            if not name or event['status'] not in ('ok', 'err', 'exception', 'skip', 'ignore'):
                continue
            result[(row['file'], name)] = event['status']
    return result, report['binary_sha256']


out = Path(sys.argv[1])
pre1, pre1_sha = statuses(sys.argv[2])
pre2, pre2_sha = statuses(sys.argv[3])
post1, post1_sha = statuses(sys.argv[4])
post2, post2_sha = statuses(sys.argv[5])
names = sorted(set(pre1) | set(pre2) | set(post1) | set(post2))
gained, lost, per_file = [], [], {}
for key in names:
    pre_ok = pre1.get(key) == 'ok' and pre2.get(key) == 'ok'
    post_ok = post1.get(key) == 'ok' and post2.get(key) == 'ok'
    counts = per_file.setdefault(key[0], dict(pre_both_ok=0, post_both_ok=0))
    counts['pre_both_ok'] += pre_ok
    counts['post_both_ok'] += post_ok
    if post_ok and not pre_ok:
        gained.append(dict(file=key[0], test=key[1], pre=[pre1.get(key), pre2.get(key)]))
    if pre_ok and not post_ok:
        lost.append(dict(file=key[0], test=key[1], post=[post1.get(key), post2.get(key)]))
record = dict(binaries=dict(pre_1s=pre1_sha, pre_2s=pre2_sha, post_1s=post1_sha, post_2s=post2_sha),
              per_file=per_file, gained=gained, lost=lost)
out.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(dict(files=per_file, gained=len(gained), lost=len(lost))))
