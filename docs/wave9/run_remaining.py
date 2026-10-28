#!/usr/bin/env python3
"""Whole gate jobs only; frozen POST/ASAN, three non-overlapping server slots."""
import concurrent.futures,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];os.chdir(ROOT);os.sched_setaffinity(0,set(range(64,96)))
m=json.loads(Path('docs/wave9/correctness-matrix.json').read_text())
while not (Path('docs/wave9/jobs/final-once.json').exists() and Path('build/wave9/remaining-ready').exists()):time.sleep(10)
sha=hashlib.sha256(Path('build/tomokv').read_bytes()).hexdigest()
asan=ROOT/'build/tomokv-wave9-ASAN';shutil.copy2('build/gate-cache/tomokv-asan',asan)
Path('docs/wave9/frozen-asan.json').write_text(json.dumps(dict(path=str(asan),sha256=hashlib.sha256(asan.read_bytes()).hexdigest()),indent=2)+'\n')
groups=[[],[],[]]
groups[0].append(('repair-rechecks',m['repair_rechecks'],[]))
groups[0].append(('supplemental-once',m['supplemental_once'],[]))
for engine,slot in [('uring',1),('epoll',2)]:
 groups[slot].append(('final-differ-'+engine,m['differ_each_engine'],['--engine',engine]))
 groups[slot].append(('final-engine-'+engine,m['each_engine'],['--engine',engine]))
 for fused in (False,True):
  mode='1s' if fused else '2s';options=['--engine',engine]+(['--fused'] if fused else [])
  groups[slot].append((f'final-mode-{engine}-{mode}',m['each_mode_engine'],options))
for fused in (False,True):
 groups[0].append(('final-persistence-'+('1s' if fused else '2s'),m['each_mode'],['--fused'] if fused else []))
def run(slot):
 rows=[]
 for name,jobs,opts in groups[slot]:
  assert hashlib.sha256(Path('build/tomokv').read_bytes()).hexdigest()==sha
  argv=['python3','docs/wave9/run_jobs.py',name,*jobs,'--single-slot','--server-start',str(64+8*slot),'--port',str(20020+20*slot),'--asan-binary',str(asan),*opts]
  print('START',name,flush=True);r=subprocess.run(argv)
  rows.append(dict(name=name,exit=r.returncode));print('DONE',name,r.returncode,flush=True)
  Path(f'docs/wave9/campaign-slot-{slot}.json').write_text(json.dumps(rows,indent=2)+'\n')
 return rows
with concurrent.futures.ThreadPoolExecutor(3) as pool:
 results=list(pool.map(run,range(3)))
Path('docs/wave9/remaining-campaign.json').write_text(json.dumps(results,indent=2)+'\n')
