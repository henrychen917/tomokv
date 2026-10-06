#!/usr/bin/env python3
"""Summarize exact harness journals without converting unrelated failures to passes."""
import json
from pathlib import Path

arms = []
for name, directory, count in (
    ('POST split', 'at15b-differ-split', 252),
    ('POST armed fused', 'at15b-differ-armed', 246),
    ('PRE armed fused', 'at15b-pre-differ-armed', 246),
    ('POST armed fused repeat', 'at15b-post-repeat-armed', 246),
):
    root = Path('build') / directory
    rows = []
    for line in (root / 'legs.tsv').read_text().splitlines():
        suite, atomic, seed, repeat, rc, filename = line.split('\t')
        log = root / filename
        text = log.read_text()
        coverage = json.loads(log.with_suffix(log.suffix + '.coverage.json').read_text())
        assert coverage['schema'] == 1 and coverage['commands'], log
        rows.append(dict(suite=suite, atomic=int(atomic), seed=int(seed), repeat=int(repeat),
                         exit=int(rc), log=str(log), summary=text.splitlines()[-1]))
    assert len(rows) == count, (name, len(rows))
    directed = [row for row in rows if row['suite'] in ('multi', 'multidb')]
    assert len(directed) == 12
    if name.startswith('POST'):
        assert all(row['exit'] == 0 and '0 diffs, 0 clock tolerances -> PASS' in row['summary']
                   for row in directed), directed
    else:
        for row in directed:
            text = Path(row['log']).read_text()
            assert row['exit'] == 1 and 'subexpiry=0' in text and '1 diffs' in row['summary'], row
    failed = [row for row in rows if row['exit']]
    arms.append(dict(arm=name, completed=len(rows), passed=len(rows)-len(failed),
                     failed=failed, multi_and_multidb=directed))
    print(name, ':', len(rows)-len(failed), '/', len(rows), 'suite legs pass;',
          sum(row['exit'] == 0 for row in directed), '/ 12 multi/multidb legs pass')

Path('docs/at15b/differ-results.json').write_text(json.dumps(arms, indent=2) + '\n')
