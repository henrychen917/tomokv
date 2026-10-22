"""Run finite debugger diagnostics, never a timed or throughput workload."""
import argparse,hashlib,json,os,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--arm',action='append',default=[]);p.add_argument('--label',default='references');a=p.parse_args()
refs={'headline':'/home/user/Projects/bench-bins/tomokv-headline-8656f9fa9',
      'moverfix':'/home/user/Projects/bins/moverfix-post-82a44439',
      'merged':str(ROOT/'build/wave4c/tomokv-pre'),'post':str(ROOT/'build/tomokv')}
base=ROOT/'build/wave4d'/('trace-'+a.label);base.mkdir(parents=True,exist_ok=True)
rows=[]
for arm in a.arm or ['headline','moverfix','merged']:
 for mode in ('1s','2s'):
  for atomic in (0,1):
   for depth in (1,8):
    out=base/f'{arm}-{mode}-a{atomic}-p{depth}';out.mkdir(exist_ok=False)
    cfg=dict(arm=arm,binary=refs[arm],sha256=hashlib.sha256(Path(refs[arm]).read_bytes()).hexdigest(),mode=mode,atomic=atomic,depth=depth,port=26890)
    (out/'config.json').write_text(json.dumps(cfg,indent=2)+'\n')
    command=['taskset','-c','64-71','gdb','-nx','-q','-batch','-ex','source docs/wave4d/trace_gdb.py','--args',refs[arm],
             '--port','26890','--bind','127.0.0.1','--shards','16','--databases','1','--thread-mode',mode,
             '--read-local','0','--atomic',str(atomic),'--enable-debug-command','yes','--save','','--dir',str(out)]
    if mode=='2s':command+=['--ratio','6:2']
    start=time.monotonic();env=dict(os.environ,WAVE4D_TRACE_OUT=str(out))
    with (out/'gdb.log').open('w') as log:
     proc=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
     try:rc=proc.wait(timeout=180)
     except subprocess.TimeoutExpired:
      os.killpg(proc.pid,signal.SIGTERM);rc=proc.wait(timeout=10)
    row=dict(config=cfg,argv=command,returncode=rc,seconds=time.monotonic()-start,directory=str(out))
    if (out/'result.json').exists():row['result']=json.loads((out/'result.json').read_text())
    rows.append(row);(base/'runs.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(arm,mode,atomic,depth,rc,row.get('result',{}).get('instructions_per_command','FAIL'),flush=True)
    if rc or 'result' not in row:raise SystemExit('finite diagnostic failed: '+str(out))
(ROOT/'docs/wave4d'/('instructions-'+a.label+'.json')).write_text(json.dumps(rows,indent=2)+'\n')
