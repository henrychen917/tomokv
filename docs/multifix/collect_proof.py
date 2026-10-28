#!/usr/bin/env python3
"""Collect complete gate receipts without converting failed attempts into passes."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/multifix'
def read(path):return json.loads(path.read_text())
report={'jobs':[]}
for path in sorted((OUT/'jobs').glob('*.json')):
    if path.name.endswith('.running.json'):continue
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

def ledger(name):
    rows=[]
    for line in (OUT/'jobs'/f'{name}.tsv.partial').read_text().splitlines():
        status,seconds,label=line.split('\t',2)
        if status in ('ok','FAIL'):rows.append(dict(status=status,seconds=float(seconds),label=label))
    return rows

report['directed']={}
for name,wanted in [('final-roots','ok'),('pre-directed','FAIL'),('planted-directed','FAIL')]:
    rows=[row for row in ledger(name) if row['label'].startswith('multifix ')]
    assert len(rows)==24 and all(row['status']==wanted for row in rows),(name,rows)
    report['directed'][name]=rows

affected=ledger('final-affected')
rerun=ledger('final-moverfix-paired')
failed=[row for row in affected if row['status']=='FAIL']
resolved={row['label'] for row in rerun if row['status']=='ok'}
assert len(failed)==8 and all(row['label'].startswith('moverfix ') and row['label'] in resolved for row in failed)
assert all(row['status']=='ok' for row in rerun)
report['affected_jobs']={
    'original_passes':sum(row['status']=='ok' for row in affected),
    'resolved_failures':[dict(row,rerun='final-moverfix-paired',rerun_status='ok') for row in failed],
    'unresolved_failures':[],
}

final_names=['final-differ-uring','final-differ-epoll']
final_names += [f'final-atomic-{mode}-{engine}' for mode in ('1s','2s') for engine in ('uring','epoll')]
report['final_jobs']={}
for name in final_names:
    receipt=OUT/'jobs'/f'{name}.json'
    if not receipt.exists():continue
    job=read(receipt)
    assert job['exit']==0 and job['binary_unchanged'],(name,job)
    report['final_jobs'][name]={key:job[key] for key in ('binary_sha256','summary','artifacts')}
    if name.startswith('final-atomic-'):
        mode,engine=name.removeprefix('final-atomic-').split('-')
        assert job['env']['GATE_PROOF_NO_RATES']=='1'
        assert job['env']['GATE_TXN_FUSED']==str(int(mode=='1s'))
        assert job['env']['GATE_PROOF_NET_IO']==engine
        rows=ledger(name)
        assert len(rows)==5 and all(row['status']=='ok' for row in rows)
        base=Path(job['artifacts'])/'jobs/atomic_batteries'
        output_hashes={}
        for leaf,terminal in [('torn','ATOMIC_TORN PASS'),('ryow','ATOMIC_RYOW PASS'),('hazards','FAIL=0')]:
            output=base/f'gate-atomic-{leaf}.txt'
            raw=output.read_text()
            assert terminal in raw,(name,leaf)
            if leaf=='ryow':assert 'rate comparison disabled by --no-rate-assertions' in raw
            output_hashes[str(output.relative_to(ROOT))]=hashlib.sha256(output.read_bytes()).hexdigest()
        report['final_jobs'][name]['correctness_output_sha256']=output_hashes
        report['final_jobs'][name]['throughput_experiment']='NOT RUN: GATE_PROOF_NO_RATES=1'

report['unresolved_required_checks']=[]
receipt=OUT/'jobs/final-instrument-controls.json'
if receipt.exists():
    job=read(receipt)
    log=Path(job['artifacts'])/'jobs/abba_selftest/gate-abbagate-unit.txt'
    raw=log.read_text()
    refusal='RECEIPT FIXTURE REFUSED: tests/fixtures/nullrefresh-ledger-labels.json: EXPECT_FULL=815, fixture=847, source declarations=847'
    assert job['exit']==1 and job['binary_unchanged'] and refusal in raw
    assert 'Missing fixture labels: none\nExtra fixture labels: none' in raw
    assert not any(line.startswith(('FAIL:','ERROR:','FAILED (')) for line in raw.splitlines())
    report['unresolved_required_checks'].append({
        'job':'final-instrument-controls',
        'status':'FAIL',
        'reason':refusal,
        'owner_action':'Review DQ=DF=+24 and set the owner-managed counts to 830 quick / 847 full.',
        'output':str(log.relative_to(ROOT)),
        'output_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),
        'summary':job['summary'],
    })

(OUT/'proof-summary.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({
    'attempts':len(report['jobs']),
    'promoted_assertions':{name:len(arm['assertions']) for name,arm in report['promotions'].items()},
    'directed_rows':{name:len(rows) for name,rows in report['directed'].items()},
    'affected_jobs':report['affected_jobs'],
    'final_jobs':list(report['final_jobs']),
    'unresolved_required_checks':report['unresolved_required_checks'],
    'instructions':report['instructions'],
    'freshness':report.get('freshness'),
},indent=2))
