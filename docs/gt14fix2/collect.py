import gzip,hashlib,json,re,statistics
from pathlib import Path
root=Path.cwd();out=root/'docs/gt14fix2/repeat'
progress=(root/'build/gt14fix2/release-progress.log').read_text()
stopfile=root/'build/gt14fix2/boundary-stop.json'
stop=json.loads(stopfile.read_text()) if stopfile.exists() else {}
rows=[]
for log in sorted(out.glob('release-[0-9][0-9].log')):
    text=log.read_text();number=int(log.stem[-2:])
    match=re.search(r'^  artifacts: (.+)$',text,re.M)
    tally=re.search(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL;',text)
    if not tally:continue
    assert match
    run=Path(match[1]);passed,failed=map(int,tally.groups())
    exited=re.search(rf'DONE tier=release run={number:02d} exit=(\d+) ',progress)
    if exited:exitcode=int(exited[1]);exit_source='campaign'
    else:
        assert stop.get('run')==number and stop.get('state')=='Z' and stop.get('wait_status')==0, (number,stop)
        exitcode=0;exit_source='owned gate zombie wait status captured before stopping the repetition controller'
    assert passed+failed==19,(number,passed,failed)
    row={'run':number,'artifact_directory':str(run),'passed':passed,'failed':failed,'exit':exitcode,'exit_source':exit_source,'jobs':{}}
    plan=(run/'plan.sh').read_text()
    for part in ('GATE_RATIO=6:2','GATE_SERVER_CORES=112-119','GATE_LOAD_CORES=120-127',"GATE_SERVER_SMT=''", "GATE_LOAD_SMT=''"):assert part in plan,(run,part)
    for job,total in (('debug-1',14),('atomic_batteries',4)):
        d=run/'jobs'/job;code,p,f=map(int,(d/'done').read_text().split())
        assert code==0 and p+f==total,(d,code,p,f)
        timing=(d/'family.tsv').read_text().split()
        row['jobs'][job]={'exit':code,'passed':p,'failed':f,'seconds':round(float(timing[3])-float(timing[2]),6)}
    atomic=(run/'jobs/atomic_batteries/gate-atomic-torn.txt').read_text()
    script=(run/'jobs/debug-1/gate-xscript-1.txt').read_text()
    assert atomic.rstrip().endswith('ATOMIC_TORN PASS'),run
    assert script.rstrip().endswith('XSCRIPT all directed battery passed'),run
    off=re.search(r'^  ok   OFF control exposes torn RENAME invalid=1 reads=1 errors=\[\] threads_still_alive=False hold_s=([\d.]+) witness_s=([\d.]+) ceiling_ms=30000 attempt=(\d+)/4 rerolls=(.*)$',atomic,re.M)
    on=re.search(r'^  ok   ON RENAME/MGET has exactly one live image invalid=0 reads=(\d+) final=True errors=\[\] threads_still_alive=False hold_s=([\d.]+) witness_s=([\d.]+) ceiling_ms=30000 attempt=(\d+)/4 rerolls=(.*)$',atomic,re.M)
    assert off and on and int(on[1])>0,run
    row['OFF']={'hold_s':float(off[1]),'witness_s':float(off[2]),'attempt':int(off[3]),'rerolls':off[4]}
    row['ON']={'hold_s':float(on[2]),'witness_s':float(on[3]),'attempt':int(on[4]),'rerolls':on[5],'hammer_reads':int(on[1])}
    for name,body in (('atomic_torn',atomic),('xscript',script)):
        with gzip.GzipFile(str(out/(log.stem+'-'+name+'.log.gz')),'wb',mtime=0) as stream:stream.write(body.encode())
    (out/(log.stem+'.ledger')).write_bytes((run/'ledger.partial').read_bytes())
    rows.append(row)
summary={'completed':len(rows),'requested':20,'remaining':20-len(rows),'passed_rows':sum(r['passed'] for r in rows),'failed_rows':sum(r['failed'] for r in rows),'successful_subsets':sum(r['exit']==0 and r['failed']==0 for r in rows),'test_revision':'adb9d1659','binary_sha256':hashlib.sha256((root/'build/tomokv').read_bytes()).hexdigest(),'runs':rows}
if rows:
    for arm in ('OFF','ON'):
        values=[r[arm]['hold_s'] for r in rows]
        summary[arm]={'min_s':min(values),'median_s':statistics.median(values),'max_s':max(values)}
(out/'release-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
(root/'docs/gt14fix2/release-progress.log').write_text(progress)
print({k:v for k,v in summary.items() if k!='runs'})
