#!/usr/bin/env python3
"""Count source declarations at their collector lines, independently of run logs."""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from gate_ledger_fixture import source_labels, declarations, evaluate


def inventory(source):
    start = source.index('\nstart_workers\n')
    end = source.index('\n# Every worker has reaped', start)
    quick = source.index('\nif [ "$TIER" = quick ]; then', start)
    lines = source.splitlines(keepends=True)
    marked = []
    for number, line in enumerate(lines, 1):
        offset = sum(map(len, lines[:number-1]))
        if start <= offset < end:
            line = re.sub(r'\bcollect_job\s+',
                          f'row_begin "__collector_{number}__"; collect_job ', line)
            if line.startswith('row_begin "tailgen '):
                line = f'row_begin "__collector_{number}__"; ' + line
        marked.append(line)
    rows, current = [], None
    for label in source_labels(''.join(marked)):
        marker = re.fullmatch(r'__collector_(\d+)__', label)
        if marker:
            current = int(marker[1])
        else:
            assert current is not None
            rows.append(dict(label=label, collector=current,
                             quick=current < source[:quick].count('\n') + 2))
    full = source_labels(source)
    prefix = source_labels(source[:quick] + '\n# Every worker has reaped\n')
    assert Counter(r['label'] for r in rows) == Counter(full)
    assert Counter(r['label'] for r in rows if r['quick']) == Counter(prefix)
    jobs = evaluate(declarations(source[start:end]), {}, lambda name: [name])
    jobs.remove('tailgen client-lb outstanding bound')
    return dict(quick=len(prefix), full=len(full), quick_exit_line=source[:quick].count('\n')+2,
                rows=rows, jobs=jobs)


if __name__ == '__main__':
    source = (ROOT / 'tests/gate.sh').read_text()
    before = subprocess.check_output(['git', 'show', 'e2b237926:tests/gate.sh'], cwd=ROOT, text=True)
    post, pre = inventory(source), inventory(before)
    added = Counter(r['label'] for r in post['rows']) - Counter(r['label'] for r in pre['rows'])
    removed = Counter(r['label'] for r in pre['rows']) - Counter(r['label'] for r in post['rows'])
    fixture = json.loads((ROOT/'docs/wave11/landing-label-fixture.json').read_text())['labels']
    result = dict(headline={k:pre[k] for k in ('quick','full','quick_exit_line')},
                  post=post, added=dict(added), removed=dict(removed),
                  landing_fixture_matches=Counter(fixture)==Counter(r['label'] for r in post['rows']),
                  expected_assignments=re.findall(r'^EXPECT_(?:QUICK|FULL)=\d+',source,re.M))
    (ROOT/'docs/wave11/row-inventory.json').write_text(json.dumps(result,indent=2)+'\n')
    assert result['landing_fixture_matches'] and not removed
    print('headline',pre['quick'],pre['full'],'post',post['quick'],post['full'],
          'quick exit line',post['quick_exit_line'],'added',sum(added.values()))
