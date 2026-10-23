#!/usr/bin/env python3
import argparse,concurrent.futures,gzip,hashlib,json,os,subprocess
from pathlib import Path
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64,96)))
ROOT=Path(__file__).resolve().parents[2];DOC=ROOT/os.getenv('WAVE5_INSTRUCTIONS_DOC','docs/wave5/instructions');BUILD=ROOT/os.getenv('WAVE5_COMMAND_ROOT','build/wave5/commands')
p=argparse.ArgumentParser();p.add_argument('--smoke',action='store_true');p.add_argument('--jobs',type=int,default=4);p.add_argument('--arm',choices=['pre','post']);p.add_argument('--main-only',action='store_true');a=p.parse_args()
ranges={}
for arm in ['pre','post']:
 rows=[]
 for line in subprocess.check_output(['nm','-S','--defined-only',str(BUILD/arm/'probe')],text=True).splitlines():
  f=line.split()
  if len(f)==4 and f[2].lower() in ['t','w']:rows.append([int(f[0],16),int(f[0],16)+int(f[1],16),f[3]])
 dest=DOC/(arm+'-ranges.json');dest.write_text(json.dumps(rows)+'\n');ranges[arm]=(dest,next(r[0] for r in rows if r[2]=='_Z11scope_beginv'))
def run(cell):
 arm,cmd,batch,mode,atomic,threshold=cell
 name='-'.join(map(str,cell));out=DOC/(name+'.json');log=DOC/(name+'.log')
 if out.exists():
  old=json.loads(out.read_text())
  if old.get('returncode')==0 and old.get('binary_sha256')==hashlib.sha256((BUILD/arm/'probe').read_bytes()).hexdigest():return old
 trace=BUILD/(name+'-trace.json');script=(ROOT/'docs/wave5/instructions.gdb.in').read_text()
 for key,value in dict(RANGES_FILE=repr(str(ranges[arm][0])),ANCHOR=str(ranges[arm][1]),RUN_COMMAND=repr('run '+' '.join(map(str,cell[1:]))),TRACE_FILE=repr(str(trace))).items():script=script.replace(key,value)
 gdb=BUILD/(name+'.gdb');gdb.write_text(script)
 command=['taskset','-c','80-87','gdb','-batch','-x',str(gdb),str(BUILD/arm/'probe')]
 with log.open('w') as f:
  try:rc=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,timeout=1200).returncode
  except subprocess.TimeoutExpired:rc=124
 passed='PASS bounded production command scope' in log.read_text()
 row=dict(arm=arm,command_name=cmd,batch=batch,mode=mode,atomic=atomic,slowlog=threshold,returncode=rc or int(not passed),binary_sha256=hashlib.sha256((BUILD/arm/'probe').read_bytes()).hexdigest())
 if trace.exists():
  t=json.loads(trace.read_text());pcs=t.pop('pcs');row.update(t)
  with gzip.open(DOC/(name+'-pcs.json.gz'),'wt') as f:json.dump(pcs,f)
  trace.unlink()
 out.write_text(json.dumps(row,indent=2)+'\n');print(name,row['returncode'],row.get('total'),flush=True);return row
cells=[(arm,cmd,n,mode,1,slow) for arm in ['pre','post'] for cmd in ['GET','SET'] for n in [1,32] for mode in ['1s','2s'] for slow in [10000,-1]]
cells +=[(arm,'MGET',n,mode,atomic,-1) for arm in ['pre','post'] for n in [1,8] for mode in ['1s','2s'] for atomic in [0,1]]
if a.arm:cells=[c for c in cells if c[0]==a.arm]
if a.main_only:cells=[c for c in cells if c[1]!='MGET']
if a.smoke:cells=[('pre','GET',1,'2s',1,10000),('post','GET',1,'2s',1,10000)]
with concurrent.futures.ThreadPoolExecutor(a.jobs) as pool:rows=list(pool.map(run,cells))
(DOC/('smoke.json' if a.smoke else 'runs.json')).write_text(json.dumps(rows,indent=2)+'\n')
assert all(r['returncode']==0 for r in rows)
