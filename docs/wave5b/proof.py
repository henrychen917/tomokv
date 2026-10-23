#!/usr/bin/env python3
"""Join completed partial-job evidence without treating a failed cohort as green."""
import gzip,hashlib,json,re,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave5b'
sys.path.insert(0,str(ROOT/'tests'))
from mode_equivalence import CELLS as EQ_CELLS
sha=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest()
names=['final-uring','differ-epoll-first','final-epoll','uring-extra',
       'auth-fused-uring','auth-fused-epoll']
cohorts=[];passed={};failures=[];runs={}
for name in names:
    d=DOC/'gate'/name
    r=json.loads((d/'result.json').read_text())
    assert r['binary_stable'] and r['binary_sha256']==sha
    assert r['returncode']==(1 if name=='final-uring' else 0), name
    subprocess.run(['python3',str(DOC/'archive_gate.py'),name],cwd=ROOT,check=True)
    rows=json.loads((d/'rows.json').read_text())
    bad=[x for x in rows if x['verdict']!='ok']
    if name=='final-uring':
        assert len(bad)==4 and all(x['job']=='fliplisten' for x in bad)
    else: assert not bad,name
    failures += [dict(cohort=name,**x) for x in bad]
    for row in rows:
        if row['verdict']=='ok':passed.setdefault(row['job'],[]).append(dict(cohort=name,**row))
    cohorts.append(dict(name=name,returncode=r['returncode'],passed=len(rows)-len(bad),failed=len(bad),
                        elapsed_seconds=r['elapsed'],binary_sha256=sha))
    assert len(r['run_paths'])==1
    runs[name]=Path(r['run_paths'][0])
required='iofix-hz iofix-sleep iofix-signal wb_rule_units wbland_units wb_policy netcmd_units splitlocal_units flip_unit flipfix_units flip fliplisten flip_saturated flipctl auth debug-0 debug-1'.split()
assert all(job in passed for job in required)
rerun=passed['fliplisten']
assert len(rerun)==4 and all(x['cohort']=='uring-extra' for x in rerun)
assert {x['label'] for x in failures}=={x['label'] for x in rerun}
iofix=[]
for feature,tag in [('hz','IO4.9'),('sleep','IO4.10'),('signal','IO4.17')]:
    for mode in ('2s','1s'):
        for engine in ('uring','epoll'):
            f=runs['final-uring']/f'jobs/iofix-{feature}/{feature}-{mode}-{engine}.log'
            events=[json.loads(line) for line in f.read_text().splitlines() if line.startswith('{')]
            assert any(e.get('result')=='PASS '+tag for e in events),(feature,mode,engine)
            iofix.append(dict(feature=tag,mode=mode,engine=engine,log=str(f)))
listeners=[]
for p in (runs['uring-extra']/'jobs/fliplisten').glob('fliplisten-*/*/result.json'):
    r=json.loads(p.read_text());assert r['passed'] and r['sha256']==sha and not r['errors']
    listeners.append({k:r[k] for k in ('engine','atomic','direction','outcome','arrived','served','passed')})
assert len(listeners)==16
different=[]
for engine in ('uring','epoll'):
    for mode in ('split','armed'):
        for atomic in (0,1):
            name='final-uring' if engine=='uring' else ('differ-epoll-first' if atomic==0 else 'final-epoll')
            run=runs[name];job=f'differ-{mode}-{atomic}'
            plan=json.loads((run/'differ-plan.json').read_text())
            assert plan['manifest']['permanent']==[7,19,20,23]
            expected={(suite,atomic,seed) for suite in plan['suites'] for seed in plan['manifest']['seeds']
                      if not (mode=='armed' and suite=='sort')}
            output=(run/'jobs'/job/'output.log').read_text()
            actual={(s,int(a),int(b)) for s,a,b in re.findall(r'^\s+differ (\S+) \(atomic=(\d) seed=(\d+)\)\s+ok ',output,re.M)}
            assert actual==expected,(engine,job,expected-actual,actual-expected)
            count=re.search(r'DIFFER GATE: pass=(\d+) fail=(\d+)',output)
            assert count and int(count[2])==0 and any(x['cohort']==name for x in passed[job])
            different.append(dict(engine=engine,mode=mode,atomic=atomic,seeds=plan['manifest']['seeds'],
                                  suite_legs=len(actual),passed_checks=int(count[1]),cohort=name))
    eq_name='final-uring' if engine=='uring' else 'final-epoll'
    eq=list((runs[eq_name]/'jobs/differ-equivalence/differ').glob('mode-equivalence-*/results.json'))
    assert len(eq)==1
    matrix=json.loads(eq[0].read_text())
    assert len(matrix)==len(EQ_CELLS) and {x['cell'] for x in matrix}==set(EQ_CELLS)
    assert all(x['verdict']=='ok' and x['reached'] and x['witnesses']['before']['net_io']==engine for x in matrix)
controls=[]
for arm in ('a','b'):
    expected=json.loads((DOC/f'pad-{arm}.json').read_text())['pad_sha256']
    for engine in ('uring','epoll'):
        name=f'pad-{arm}-{engine}';d=DOC/'gate'/name;r=json.loads((d/'result.json').read_text())
        assert r['binary_sha256']==expected and r['binary_stable'] and r['returncode']==0
        subprocess.run(['python3',str(DOC/'archive_gate.py'),name],cwd=ROOT,check=True)
        rows=json.loads((d/'rows.json').read_text());assert all(x['verdict']=='ok' for x in rows)
        controls.append(dict(cohort=name,sha256=expected,passed=len(rows),modes=['1s','2s'],policies=[0,1]))
fresh=json.loads((DOC/'freshness.json').read_text())
assert fresh['build_returncode']==0 and len(fresh['checks'])==45 and all(x['returncode']==0 for x in fresh['checks'])
identity=json.loads((DOC/'identity/summary.json').read_text())
assert all(r['main_groups']==r['main_groups_equal']==12 for r in identity.values())
record=dict(binary_sha256=sha,cohorts=cohorts,required_jobs=required,
    all_required_jobs_have_passing_receipts=True,iofix_legs=iofix,listener_legs=listeners,
    differential=different,mode_equivalence_cells_per_engine=len(EQ_CELLS),control_checks=controls,
    resolved_failures=failures,
    resolution='The first fliplisten cohort passed an adapter script to GDB; all 16 legs passed on the same frozen ELF in uring-extra.',
    gates_test=json.loads((DOC/'gates-test.json').read_text()),row_accounting=json.loads((DOC/'row-inventory.json').read_text()),
    not_run=[dict(item='performance benchmarks / ABBA / PMU rate measurements',reason='reserved to maintainer'),
             dict(item='full tests/gate.sh iteration',reason='reserved to maintainer; only selected correctness jobs ran'),
             dict(item='fused SORT differential legs',reason='standard differential plan declares SORT split-only'),
             dict(item='fused FLIP',reason='FLIP is a split-mode feature')],
    note='Partial-job observations are not a full-gate receipt. Initial failed launch and self-test evidence is retained.')
(DOC/'proof.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(dict(cohorts=len(cohorts),passed=sum(x['passed'] for x in cohorts),
    resolved_launch_failures=len(failures),differential_suite_legs=sum(x['suite_legs'] for x in different),
    differential_checks=sum(x['passed_checks'] for x in different)),indent=2))
