#!/usr/bin/env python3
"""Check completed selected-job groups and explicit live-leg inventories."""
import hashlib,itertools,json,re
from pathlib import Path
from execfifo3_validate import GROUPS
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/execfifo3/validation'
rows=json.loads((OUT/'runs.json').read_text())
sha=hashlib.sha256((ROOT/'build/execfifo3/POST').read_bytes()).hexdigest()
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
if 'directed' in latest:
    run=Path(latest['directed']['run_directory'])/'jobs/txnorder_chain'
    expected={f'{case}-{unit}-{mode}.log' for case,unit,mode in itertools.product(
        ('local','boundary','serve','hot'),('txnorder-chain-unit','txnorder-chain-db0-unit'),('1s','2s'))}
    legs=list(run.glob('*-txnorder-chain-*.log'))
    summary['leg_inventories'].append(dict(job='txnorder_chain',expected=len(expected),actual=len(legs),passed={file.name for file in legs}==expected and all('PASS' in file.read_text() and 'FAIL' not in file.read_text() for file in legs),source=str(run)))
if 'fairness' in latest:
    run=Path(latest['fairness']['run_directory'])/'jobs/txnorder_fifo_live'
    expected={f'fifo-{databases}-{mode}-{atomic}-{engine}.json' for databases,mode,atomic,engine in itertools.product(
        (1,16),('1s','2s'),(0,1),('uring','epoll'))}
    legs=list(run.glob('fifo-*.json')); witnesses=[]
    for file in legs:
        evidence=json.loads(file.read_text());windows=evidence.get('windows',[])
        good=(evidence.get('pass') is True and evidence.get('seconds')==60 and
              evidence.get('protocol_ready_clients')==68 and len(windows)==60 and
              [row['index'] for row in windows]==list(range(60)) and
              all(len(row['completions'])==68 and min(row['completions'])>0 for row in windows) and
              evidence.get('actual')==evidence.get('expected') and
              evidence.get('deltas',{}).get('atomic_txn_fifo_waits',0)>0)
        witnesses.append(dict(file=file.name,windows=len(windows),passed=good))
    summary['leg_inventories'].append(dict(job='txnorder_fifo_live',expected=len(expected),actual=len(legs),passed={file.name for file in legs}==expected and all(row['passed'] for row in witnesses),witnesses=witnesses,source=str(run)))
for engine in ('uring','epoll'):
    if 'differ-'+engine not in latest:continue
    run=Path(latest['differ-'+engine]['run_directory'])
    plan=json.loads((run/'differ-plan.json').read_text())
    for mode in ('split','armed'):
        for atomic in (0,1):
            file=run/'jobs'/f'differ-{mode}-{atomic}'/'differ/legs.tsv'
            legs=[line.split('\t') for line in file.read_text().splitlines()]
            expected={(suite,str(atomic),str(seed),'0') for suite in plan['suites'] for seed in plan['manifest']['seeds'] if mode!='armed' or suite!='sort'}
            if atomic:
                expected.update(('multi','1','19',str(repeat)) for repeat in range(1,plan['repeats']+1))
            observed={tuple(leg[:4]) for leg in legs}
            summary['leg_inventories'].append(dict(job=f'differ-{engine}-{mode}-{atomic}',expected=len(expected),actual=len(legs),seeds=plan['manifest']['seeds'],passed=observed==expected and len(legs)==len(expected) and all(leg[4]=='0' for leg in legs),source=str(file)))
summary['passed']=not missing and not failed and all(r['passed_rows']>0 and r['failed_rows']==0 for r in summary['groups']) and all(r['passed'] for r in summary['leg_inventories'])
allocation=dict(logs_with_banners=0,ports=set(),server_cpus=set(),outside_allocation=[])
for row in rows:
    for file in Path(row['run_directory']).rglob('*'):
        if not file.is_file() or not (file.name.startswith('gate-srv-') or file.name=='server.log'):continue
        text=file.read_text(errors='replace')
        ports=set(map(int,re.findall(r'(?:listening on [^\s:]+:|port=)(\d+)',text)))
        cpus=set(map(int,re.findall(r'\bthread t\d+:.*?\bcpu=(\d+)',text)))
        allocation['logs_with_banners']+=bool(ports or cpus)
        allocation['ports'].update(ports);allocation['server_cpus'].update(cpus)
        if not ports<=set(range(20600,20700)) or not cpus<=set(range(96,112)):
            allocation['outside_allocation'].append(str(file))
allocation['ports']=sorted(allocation['ports']);allocation['server_cpus']=sorted(allocation['server_cpus'])
summary['boot_allocation']=allocation
summary['passed'] &= not allocation['outside_allocation']
(OUT/'coverage.json').write_text(json.dumps(summary,indent=2)+'\n')
print('required groups',len(GROUPS),'missing',missing,'failed',failed,'leg inventory',summary['leg_inventories'])
assert summary['passed']
