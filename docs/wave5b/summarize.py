#!/usr/bin/env python3
"""Summarize only uncontended mechanism cohorts; never infer rates from counts."""
import json
from pathlib import Path
from statistics import median

DOC = Path(__file__).resolve().parent
result = []
for cohort in ('attribution', 'adaptive-quiet'):
    rows = [json.loads(p.read_text()) for p in (DOC/cohort).glob('*/result.json')]
    for arm in sorted({r['arm'] for r in rows}):
        for command, atomic in [('MGET',1), ('MGET',0), ('MSET',1)]:
            sample = [r for r in rows if (r['arm'],r['command'],r['atomic']) == (arm,command,atomic)]
            assert len(sample) == 3
            assert all(r['counts'][k] > 0 for r in sample for k in ('visits','deferrals','sends','completions'))
            if cohort == 'attribution':
                assert all((r['counts']['parks_pending'] > 0) == (arm == 'post') for r in sample), 'park attribution not reproduced'
            result.append(dict(cohort=cohort, arm=arm, command=command, atomic=atomic,
                requests_per_repeat=sample[0]['requests'],
                raw_pending_parks=[r['counts']['parks_pending'] for r in sorted(sample,key=lambda r:r['repeat'])],
                median_per_request={k:median(r['per_request'][k] for r in sample) for k in sample[0]['counts']},
                sha256=sample[0]['binary_sha256']))
(DOC/'mechanism-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print('| Cohort | Arm | Command / atomic | Parks with pending | Wake messages | FIFO visits | Send submissions |')
print('|---|---|---|---:|---:|---:|---:|')
for r in result:
    c=r['median_per_request']
    print(f"| {r['cohort']} | {r['arm']} | {r['command']} / {r['atomic']} | " +
          ' | '.join(f'{c[k]:.6f}' for k in ('parks_pending','wakes','visits','sends'))+' |')
