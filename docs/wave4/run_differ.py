#!/usr/bin/env python3
"""The unchanged standard differ_gate matrices, both engines and geometries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import run_proof

ROOT=run_proof.ROOT
OUT=ROOT/'build/wave4/differ'
DOC=ROOT/'docs/wave4/differ'


def engine_run(engine):
    servers,oracle,clients,port = ('64-71','72','73-79',26860) if engine=='uring' else ('96-103','104','105-111',26862)
    binary=ROOT/'build/tomokv'
    wrapper=OUT/('tomokv-'+engine)
    wrapper.write_text('#!/bin/bash\nexec '+str(binary)+' --net-io '+engine+' "$@"\n')
    wrapper.chmod(0o755)
    results=[]
    for geometry in ('split','armed-fused'):
        dest=DOC/(engine+'-'+geometry); dest.mkdir(parents=True,exist_ok=False)
        env=dict(os.environ,REDIS74_ROOT=str(ROOT/'build/wave4/oracle'),
                 GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
                 GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli',
                 GATE_DIFFER_ORACLE_CORES=oracle,GATE_LOAD_CORES=clients,
                 GATE_RUN_ID='wave4b-final-standard',GATE_DIFFER_GEOMETRY=geometry,
                 GATE_DIFFER_OUT=str(OUT/(engine+'-'+geometry)),GATE_TEST_PORT='26899')
        argv=['taskset','-c',clients,'bash','tests/differ_gate.sh',str(wrapper),str(port),str(port+1),servers,'6:2']
        result=dict(argv=argv,env={k:v for k,v in env.items() if k.startswith(('GATE_','REDIS74'))},
                    binary=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
        (dest/'command.json').write_text(json.dumps(result,indent=2)+'\n')
        start=time.monotonic()
        with (dest/'output.log').open('w') as stream:
            result['returncode']=subprocess.run(argv,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT).returncode
        result['seconds']=time.monotonic()-start
        (dest/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        results.append(result)
        print(engine,geometry,result['returncode'],flush=True)
    return results


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True);DOC.mkdir(parents=True,exist_ok=True)
    run_proof.setup()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=[r for group in pool.map(engine_run,('uring','epoll')) for r in group]
    (DOC/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    raise SystemExit(any(r['returncode'] for r in results))
