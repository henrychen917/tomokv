#!/usr/bin/env python3
"""Replay the harness5 root scripts with the pinned oracle, preserving RESP types."""
import argparse, hashlib, importlib.util, json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('h5', ROOT/'docs/harness5/repro_tcl.py')
h5 = importlib.util.module_from_spec(spec); spec.loader.exec_module(h5)
ORACLE = Path('/home/user/Projects/redis74/src/redis-server')
ROOTS = ('MULTI-OOM-QUEUE', 'MULTI-OOM-EXEC', 'RESET-IN-MULTI',
         'PAUSE-IN-MULTI', 'PAUSE-EXEC-NOT-HELD', 'SLOWLOG-EXEC-BODY-NOT-LOGGED',
         'MULTI-POLICY-REFUSAL')
def main():
    p=argparse.ArgumentParser();p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--port',type=int,default=20500)
    p.add_argument('--cores',default='32-39');p.add_argument('--ratio',default='6:2')
    p.add_argument('--engine',default='uring');a=p.parse_args();a.binary=a.binary.resolve()
    a.output.mkdir(parents=True,exist_ok=True)
    cases=json.loads((ROOT/'docs/harness5/redis-tcl-repro-cases.json').read_text())
    out={'binary_sha256':h5.hashlib.sha256(a.binary.read_bytes()).hexdigest(),
         'redis_sha256':h5.hashlib.sha256(ORACLE.read_bytes()).hexdigest(),'cases':{}}
    for ident in ROOTS:
        case=cases[ident]; results={}
        for mode,binary in [('2s',a.binary),('1s',a.binary),('redis',ORACLE)]:
            selected=dict(case)
            if mode!='redis':selected['server_args']=['--net-io',a.engine]
            results[mode]=h5.play(selected,mode,binary,a,a.output/ident/mode)
        out['cases'][ident]={'results':results,'verdict':h5.verdict(results)}
        print(ident,out['cases'][ident]['verdict'],flush=True)
        (a.output/'results.json').write_text(json.dumps(out,indent=2)+'\n')
if __name__=='__main__':main()
