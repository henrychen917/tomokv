#!/usr/bin/env python3
"""Bind the lane's bounded counts, frozen images and individual-job verdicts."""
import json,re,subprocess
from pathlib import Path
import exec1sd as d

def read(name):return json.loads((d.DOCS/name).read_text())
def key(row):return tuple(row[k] for k in ('namespace','command','mode','batch','atomic'))
def compare(before,after):
 old={key(r):r for r in before};new={key(r):r for r in after}
 assert old.keys()==new.keys()
 return [dict(zip(('namespace','command','mode','batch','atomic'),k),pre=old[k]['total'],
              post=new[k]['total'],delta=new[k]['total']-old[k]['total']) for k in sorted(old)]
def counts():
 arms=read('arms.json');manifest={r['arm']:r for r in arms}
 for row in arms:assert d.sha(row['binary'])==row['sha256'],row['arm']
 ordinary=compare(read('ORD-PRE-counts.json'),read('ORD-POST-counts.json'))
 local=compare(read('RL-PRE-counts.json'),read('RL-POST-counts.json'))
 idle=compare(read('IDLE-X12-counts.json'),read('IDLE-POST-counts.json'))
 assert len(ordinary)==48 and len(local)==4 and len(idle)==2
 for arm,kinds in [('PRE',['ORD','RL','EXEC']),('POST',['ORD','RL','EXEC','IDLE']),('REUSE',['EXEC'])]+[(a,['EXEC','IDLE']) for a in ('X12','X3','X5','MERGE')]:
  retired=read(arm+'-probe-retirements.json')
  for kind in kinds:
   data=read(kind+'-'+arm+'-counts.json')
   assert len(data)=={'ORD':48,'RL':4,'EXEC':72,'IDLE':2}[kind]
   for ns in ('normal','db0'):
    receipt=next(r for r in retired if r.get('kind')==kind and r.get('namespace')==ns)
    assert receipt['production_sha256']==manifest[arm]['sha256'],(arm,kind,ns)
    assert receipt['count_sha256']==d.sha(d.DOCS/(kind+'-'+arm+'-counts.json'))
    assert all(r['probe_sha256']==receipt['sha256'] for r in data if r['namespace']==ns)
 alloc=[]
 for ns in ('normal','db0'):
  pre=read('C-PRE-allocation-'+ns+'.json');post=read('POST-allocation-'+ns+'.json')
  assert post['production_sha256']==manifest['POST']['sha256']
  a=next(r for r in pre['results'] if r['mode']=='1s')['prepare_total_bytes']
  b=next(r for r in post['results'] if r['mode']=='1s')['prepare_total_bytes']
  split=next(r for r in post['results'] if r['mode']=='2s')['prepare_total_bytes']
  alloc.append(dict(namespace=ns,pre=a,post=b,ratio=b/a,split=split,geometry_ratio=b/split,
                    passed=b<=a/4 and b<=split*1.2))
 attribution={name:compare(read('EXEC-'+pre+'-counts.json'),read('EXEC-'+post+'-counts.json'))
              for name,pre,post in [('X3','X12','X3'),('X5','X12','X5'),('X5-with-X3','X3','MERGE'),
                                    ('reuse-only','PRE','REUSE'),('final','PRE','POST')]}
 d.save(d.DOCS/'count-comparison.json',dict(scope='All named linked production instructions, including executed NOPs; fixture glue and external library callees excluded. Exact replies mandatory.',
  production_sha256=manifest['POST']['sha256'],ordinary=ordinary,read_local=local,idle=idle,
  allocation=alloc,attribution=attribution,ordinary_pass=all(r['delta']<=0 for r in ordinary),
  read_local_pass=all(r['delta']==0 for r in local),idle_pass=all(r['delta']<=2 for r in idle),
  allocation_pass=all(r['passed'] for r in alloc)))
 print('counts: ordinary max',max(r['delta'] for r in ordinary),'read-local max',max(r['delta'] for r in local),
       'idle',[(r['namespace'],r['delta']) for r in idle],'allocation',[(r['namespace'],r['ratio']) for r in alloc])

def proof():
 manifest={r['arm']:r for r in read('arms.json')};runs=[]
 for path in sorted((d.OUT/'proof').glob('*.json')):
  receipt=json.loads(path.read_text());log=Path(receipt['log'])
  row=dict(receipt=str(path),receipt_sha256=d.sha(path),log_sha256=d.sha(log),**receipt)
  row['jobs']=[]
  if receipt.get('artifacts'):
   root=Path(receipt['artifacts']);row['plan_sha256']=d.sha(root/'plan.sh')
   if (root/'differ-plan.json').exists():row['differ_plan']=json.loads((root/'differ-plan.json').read_text())
   for folder in sorted((root/'jobs').glob('*')):
    job=dict(name=folder.name,completed=(folder/'done').exists())
    if (folder/'ledger').exists():
     rows=[line.split('\t',2) for line in (folder/'ledger').read_text().splitlines()]
     job.update(rows=rows,ledger_sha256=d.sha(folder/'ledger'),passed=sum(r[0]=='ok' for r in rows),failed=sum(r[0]=='FAIL' for r in rows))
    if job['completed']:job['done']=(folder/'done').read_text().strip()
    for name in ['differ/legs.tsv','differ/complete.json']:
     file=folder/name
     if file.exists():job[name]=dict(sha256=d.sha(file),data=file.read_text())
    row['jobs'].append(job)
  row['bound_to_final_post']=receipt.get('candidate_sha256')==manifest['POST']['sha256']
  runs.append(row)
 final_jobs={}
 for run in sorted(runs,key=lambda r:r['started_utc']):
  if not run['bound_to_final_post']:continue
  for job in run['jobs']:
   if job['completed']:final_jobs[job['name']]=dict(invocation=run['receipt'],**job)
 d.save(d.DOCS/'live-proof.json',dict(production_sha256=manifest['POST']['sha256'],runs=runs,final_jobs=final_jobs,
  not_run=[dict(job=name,reason=reason) for name,reason in [
   ('full gate iteration / performance merit','Maintainer-only; all invoked gates use GATE_ONLY_JOBS.'),
   ('flip_saturated and atomic_floor','Invoke memtier, which is outside lane runtime authorization.'),
   ('atomic_ryow rate assertion','Existing GATE_PROOF_NO_RATES=1 partial interface; finite correctness schedules retained.')]]))
 print('proof invocations',len(runs),'completed final jobs',len(final_jobs),'failed final rows',sum(j.get('failed',0) for j in final_jobs.values()))

if __name__=='__main__':counts();proof()
