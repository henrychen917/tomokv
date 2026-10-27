#!/usr/bin/env python3
"""Collect complete gate receipts without converting failed attempts into passes."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/multifix'
def read(path):return json.loads(path.read_text())
report={'jobs':[]}
for path in sorted((OUT/'jobs').glob('*.json')):
    row=read(path)
    report['jobs'].append({k:row.get(k) for k in ('source_commit','binary_sha256','binary_unchanged','exit','seconds','summary','artifacts')}|{'name':path.stem})
promotions=read(OUT/'tcl-promotions.json')
report['promotions']={}
for name,wanted in [('final-affected','ok'),('final-planted-tcl','err')]:
    receipt=OUT/'jobs'/f'{name}.json'
    if not receipt.exists():continue
    job=read(receipt);base=Path(job['artifacts'])/'jobs/redis_tcl'
    rows=[]
    for mode in ('1s','2s'):
        summary=read(base/f'redis-tcl-{mode}'/'summary.json')
        units={row['file']:row for row in summary['rows']}
        for unit,names in promotions.items():
            for test in names:
                matching=[e for e in units[unit]['events'] if e['status'] in ('ok','err') and
                          e['test'].split(' in tests/')[0]==test]
                assert len(matching)==1 and matching[0]['status']==wanted,(name,mode,unit,test,matching)
                rows.append(dict(mode=mode,unit=unit,name=test,**{k:matching[0][k] for k in ('status','data')}))
    report['promotions'][name]=dict(binary_sha256=job['binary_sha256'],assertions=rows)
    report['promotions'][name]['arming']={mode:next(r for r in read(base/f'redis-tcl-{mode}'/'summary.json')['rows']
        if r['file']=='unit/type/set')['smove_layout_attempts'] for mode in ('1s','2s')}
    assert all(attempts and attempts[-1]['armed'] for attempts in report['promotions'][name]['arming'].values())
report['instructions']=read(OUT/'instructions/comparison.json')['all_zero_added_instructions']
if (OUT/'freshness.json').exists():report['freshness']=read(OUT/'freshness.json')['all_fresh']
(OUT/'proof-summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='promotions'},indent=2))
