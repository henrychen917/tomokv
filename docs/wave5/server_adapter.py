#!/usr/bin/env python3
"""Gate adapter: keep positional config first, preserve explicit leg options."""
import json,os,sys
from pathlib import Path
root=Path(__file__).resolve().parents[2]
a=sys.argv[1:];engine=os.environ.get('WAVE5_ENGINE');mode=os.environ.get('WAVE5_MODE')
def has(option):return any(x==option or x.startswith(option+'=') for x in a)
extra=[]
if engine and not has('--net-io'):extra+=['--net-io',engine]
if mode and not has('--thread-mode'):
 if mode=='1s':
  out=[];i=0
  while i<len(a):
   x=a[i];i+=1
   if x=='--ratio':i+=1;continue
   if x.startswith('--ratio='):continue
   out.append(x)
  a=out
 extra+=['--thread-mode',mode]
# Append only missing defaults. The parser's first positional config stays first.
a+=extra
binary=Path(os.environ.get('WAVE5_BINARY',str(root/'build/tomokv')))
log=os.environ.get('WAVE5_LAUNCH_DIR')
if log:
 p=Path(log);p.mkdir(parents=True,exist_ok=True)
 (p/(str(os.getpid())+'.json')).write_text(json.dumps(dict(binary=str(binary),argv=a,affinity=sorted(os.sched_getaffinity(0))))+'\n')
os.execv(binary,[str(binary),*a])
