#!/usr/bin/env python3
"""wave2: summarize the 20 gate runs of feature-split-0/1 (infofix20.sh output): one row per run,
both infofix rows, every other row of the run, and whether any INFOFIX output reported avg_ttl.
usage: infofix_summary.py <infofix20-dir> <out.json>"""
import json, re, sys
from pathlib import Path
d = Path(sys.argv[1])
runs = []
for line in (d / 'summary.txt').read_text().splitlines():
    m = re.match(r'run (\d+) exit=(\d+) seconds=(\d+)', line)
    if not m:
        continue
    i = int(m[1])
    ledger = (d / f'run-{i}.ledger.partial').read_text().splitlines()
    rows = [l.split('\t') for l in ledger if l.startswith(('ok\t', 'FAIL\t'))]
    infofix = {}
    for a in (0, 1):
        out = d / f'run-{i}-infofix-{a}.txt'
        text = out.read_text(errors='replace') if out.exists() else ''
        status = next((r[0] for r in rows if r[2] == f'infofix battery (atomic {a})'), 'missing')
        infofix[a] = dict(row=status, passed_line='INFOFIX: PASS' in text,
                          checks=(re.search(r'INFOFIX: PASS \((\d+) checks\)', text) or [None, None])[1],
                          avg_ttl_failures=[l.strip() for l in text.splitlines() if 'avg_ttl' in l and 'FAIL' in l])
    runs.append(dict(run=i, exit_code=int(m[2]), seconds=int(m[3]), rows_ok=sum(r[0] == 'ok' for r in rows),
                     rows_fail=[r[2] for r in rows if r[0] == 'FAIL'], infofix=infofix))
summary = dict(runs=len(runs),
               infofix_atomic0_ok=sum(r['infofix'][0]['row'] == 'ok' for r in runs),
               infofix_atomic1_ok=sum(r['infofix'][1]['row'] == 'ok' for r in runs),
               avg_ttl_failures=sum(len(r['infofix'][a]['avg_ttl_failures']) for r in runs for a in (0, 1)),
               other_failed_rows=sorted({x for r in runs for x in r['rows_fail']}),
               rows_ok_per_run=sorted({r['rows_ok'] for r in runs}),
               seconds=[r['seconds'] for r in runs])
Path(sys.argv[2]).write_text(json.dumps(dict(summary=summary, runs=runs), indent=1) + '\n')
print(json.dumps(summary))
