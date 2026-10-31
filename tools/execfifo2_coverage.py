#!/usr/bin/env python3
"""Check completed selected-job groups and explicit live-leg inventories."""
import hashlib,json
from pathlib import Path
from execfifo2_validate import GROUPS
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/execfifo2/validation'
rows=json.loads((OUT/'runs.json').read_text())
sha=hashlib.sha256((ROOT/'build/execfifo2/POST').read_bytes()).hexdigest()
latest={r['group']:r for r in rows if r['binary_sha256']==sha}
missing=sorted(set(GROUPS)-set(latest));failed=[name for name,r in latest.items() if r['exit_code']]
summary=dict(required_groups=sorted(GROUPS),missing_groups=missing,failed_latest_groups=failed,production_sha256=sha,attempts=len(rows),failed_attempts=[r['group'] for r in rows if r['exit_code']],groups=[],leg_inventories=[])
for name,r in sorted(latest.items()):
    ledger=Path(r['run_directory'])/'ledger.partial'
    scored=[line.split('\t',2) for line in ledger.read_text().splitlines()
            if line.startswith(('ok\t','FAIL\t'))]
    summary['groups'].append(dict(group=name,returncode=r['exit_code'],passed_rows=sum(row[0]=='ok' for row in scored),failed_rows=sum(row[0]=='FAIL' for row in scored),ledger=str(ledger)))
if 'at412' in latest:
    run=Path(latest['at412']['run_directory'])
    for case in 'T1 T2 T3 T4 T5 T6 T7 T8 T9 T10 T11a T11b T12 T13 T14 T15 T16'.split():
        file=run/'jobs'/('at412-'+case)/('at412-'+case)/'results.json'
        legs=json.loads(file.read_text());expected=15 if case in ('T3','T10','T11a') else 27
        good=len(legs)==expected and len({r['leg'] for r in legs})==expected and all(r.get('pass') for r in legs)
        summary['leg_inventories'].append(dict(job='at412-'+case,expected=expected,actual=len(legs),passed=good,source=str(file)))
if 'fifo-contract' in latest:
    run=Path(latest['fifo-contract']['run_directory'])/'jobs/txnorder_fifo'
    legs=list(run.glob('F*-txnorder-fifo-*.log'))
    expected=10*2*2*2*2
    summary['leg_inventories'].append(dict(job='txnorder_fifo',expected=expected,actual=len(legs),passed=len(legs)==expected and all('PASS' in file.read_text() and 'FAIL' not in file.read_text() for file in legs),source=str(run)))
summary['passed']=not missing and not failed and all(r['passed_rows']>0 and r['failed_rows']==0 for r in summary['groups']) and all(r['passed'] for r in summary['leg_inventories'])
(OUT/'coverage.json').write_text(json.dumps(summary,indent=2)+'\n')
print('required groups',len(GROUPS),'missing',missing,'failed',failed,'leg inventory',summary['leg_inventories'])
assert summary['passed']
