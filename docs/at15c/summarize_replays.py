#!/usr/bin/env python3
"""Preserve unmodified full replay verdicts and the two seed-7 PTTL differences."""
import ast
import json
from pathlib import Path
import re
import shutil

ops = json.loads(Path('docs/at15c/edgetime-seed7.json').read_text())
rows = []
for out in sorted(Path('build/at15c').glob('replay-*')):
    log = out / 'edgetime-a0-s7.txt'
    if not log.exists():
        continue
    data = log.read_text()
    completion = out / 'complete.json'
    summary = re.search(r'DIFFER edgetime: (\d+) ops, (\d+) diffs, (\d+) clock tolerances -> (\w+)', data)
    if not summary:
        continue
    differences = {}
    raw = {}
    for match in re.finditer(r'DIFF op (\d+) (.+)\n    target: (.+)\n    oracle: (.+)', data):
        index = int(match[1])
        a, b = ast.literal_eval(match[3]), ast.literal_eval(match[4])
        raw[index] = dict(target=repr(a), oracle=repr(b))
        if a.startswith(b':') and b.startswith(b':'):
            differences[index] = int(a[1:-2]) - int(b[1:-2])
    tolerances = {}
    for match in re.finditer(r'CLOCK TOLERANCE .* command=(.+)\n    target: (.+)\n    oracle: (.+)', data):
        command = ast.literal_eval(match[1])
        if command[0] == 'PTTL':
            a, b = ast.literal_eval(match[2]), ast.literal_eval(match[3])
            tolerances[command[1]] = dict(delta_ms=int(a[1:-2])-int(b[1:-2]),
                                         target=repr(a), oracle=repr(b))
    outer = Path('docs/at15c') / (out.name + '.log')
    matrix = re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+) runtime=(\S+)',
                       outer.read_text() if outer.exists() else '')
    row = dict(run=out.name, edgetime=summary[4], diffs=int(summary[2]),
               clock_tolerances=int(summary[3]), matrix_finished=bool(matrix),
               passing_fold=completion.exists(), operations={})
    if matrix:
        row['matrix'] = dict(passed=int(matrix[1]), failed=int(matrix[2]), runtime=matrix[3])
        legs = [line.split('\t') for line in (out / 'legs.tsv').read_text().splitlines()]
        row['suite_legs'] = len(legs)
        row['suite_legs_passed'] = sum(leg[4] == '0' for leg in legs)
        row['failed_legs'] = [dict(suite=leg[0], seed=int(leg[2]), rc=int(leg[4]))
                              for leg in legs if leg[4] != '0']
    if completion.exists():
        row['fold'] = json.loads(completion.read_text())
    for index in (1526, 2910):
        if index in differences:
            value = dict(delta_ms=differences[index], **raw[index], evidence='printed DIFF')
        elif ops[index][1] in tolerances:
            value = dict(**tolerances[ops[index][1]], evidence='printed key-specific CLOCK TOLERANCE')
        else:
            assert int(summary[2]) <= 12, 'diff printing limit prevents inference of equality'
            value = dict(delta_ms=0, evidence='exact equality: neither DIFF nor CLOCK TOLERANCE')
        row['operations'][index] = value
    rows.append(row)
    shutil.copy2(log, Path('docs/at15c') / (out.name + '-edgetime.log'))
Path('docs/at15c/reproduction.json').write_text(json.dumps(rows, indent=2) + '\n')
for row in rows:
    print(row['run'], row['edgetime'], 'finished=' + str(row['matrix_finished']),
          'd1526=' + str(row['operations'][1526]['delta_ms']),
          'd2910=' + str(row['operations'][2910]['delta_ms']))
