#!/usr/bin/env python3
"""Fresh correctness servers on the lane allocation, with captured child output."""
import argparse,importlib.util,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('reproduce',ROOT/'docs/multifix/reproduce.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
def main():
 p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
 p.add_argument('--cases',default='RESET-IN-MULTI,WATCH-SPURIOUS-INVALIDATION');p.add_argument('--modes',default='2s,1s,redis')
 p.add_argument('--engine',default='uring');p.add_argument('--atomic',type=int,default=0);p.add_argument('--read-local',type=int,default=0)
 a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True);rows=[]
 for mode in a.modes.split(','):
  for root in a.cases.split(','):
   folder=a.output/(mode+'-'+root)
   binary=r.ORACLE if mode=='redis' else a.binary.resolve()
   extra=[] if mode=='redis' else ['--net-io',a.engine,'--atomic',a.atomic,'--read-local',a.read_local]
   proc,cmd=r.h5.boot(mode,binary,20500,'32-39','6:2',extra,folder)
   try:
    result=subprocess.run(['python3','tests/multifix.py','127.0.0.1','20500','--case',root]+(['--oracle'] if mode=='redis' else []),cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=120)
    (folder/'test.log').write_text(result.stdout)
    rows.append(dict(mode=mode,root=root,exit_code=result.returncode,argv=cmd))
    print(mode,root,result.returncode,flush=True)
   finally:r.h5.stop(proc)
 (a.output/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
if __name__=='__main__':main()
