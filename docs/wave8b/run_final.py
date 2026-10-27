#!/usr/bin/env python3
"""Serial correctness jobs: one eight-core server slot, no performance tier."""
import hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT);os.sched_setaffinity(0,set(range(64,80)))
matrix=json.loads((ROOT/'docs/wave8/correctness-matrix.json').read_text())
once=matrix['once']+['wave8b_off','authfix','bugs5','ntfix_input','netfix_query_stats',
    'persistfix2_lastsave','racefix_counters']
campaign=[('final-lanes',once,[]),('final-tcl',['compat2'],[])]
for engine in ('uring','epoll'):
 campaign += [('final-engine-'+engine,matrix['each_engine'],['--engine',engine])]
 for fused in (False,True):
  mode='1s' if fused else '2s'
  campaign += [(f'final-debug-{engine}-{mode}',matrix['each_mode_engine']+['notify'],['--engine',engine]+(['--fused'] if fused else []))]
 campaign += [('final-differ-'+engine,matrix['differ_each_engine'],['--engine',engine])]
# AOF includes the latency/delayed-fsync witnesses, in both modes and engines.
for fused in (False,True):
 campaign += [('final-aof-'+('1s' if fused else '2s'),['aof-epoll','aof-uring'],['--fused'] if fused else [])]
for engine in ('uring','epoll'):
 campaign += [('final-replyoff-fused-'+engine,['replyoff'],['--engine',engine,'--fused'])]
campaign += [('final-script-aof',['notify_aof'],[])]
for engine in ('uring','epoll'):
 campaign += [('final-watch-blocking-'+engine,['exbatch_live','acl_recheck'],['--engine',engine])]
 campaign += [('final-multidb-'+engine,
     [f'multidb-{mode}-{read_local}-{atomic}' for mode in ('1s','2s')
      for read_local in (0,1) for atomic in (0,1)], ['--engine',engine])]
def main():
 sha=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest();out=[]
 for name,jobs,opts in campaign:
  assert hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest()==sha
  receipt=ROOT/'docs/wave8b/jobs'/(name+'.json')
  if not receipt.exists():
   cmd=['python3','docs/wave8b/run_jobs.py',name,*jobs,'--single-slot',*opts]
   print('START',name,flush=True);subprocess.run(cmd,check=False)
  r=json.loads(receipt.read_text());assert r['binary_sha256']==sha and r['binary_unchanged']
  out.append(dict(name=name,exit=r['exit'],summary=r['summary']))
  (ROOT/'docs/wave8b/campaign.json').write_text(json.dumps(out,indent=2)+'\n')
  print('DONE',name,r['exit'],flush=True)

if __name__=='__main__':main()
