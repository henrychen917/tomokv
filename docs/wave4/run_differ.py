#!/usr/bin/env python3
"""The unchanged standard differ_gate matrices, both engines and geometries."""
from concurrent.futures import ThreadPoolExecutor
import argparse
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
BASE_ENV={}


def matrix_run(engine,geometry,allocation):
    servers,oracle,clients,port=allocation
    binary=ROOT/'build/tomokv'
    wrapper=OUT/('tomokv-'+engine+'-'+geometry)
    wrapper.write_text('#!/bin/bash\nexec '+str(binary)+' --net-io '+engine+' "$@"\n')
    wrapper.chmod(0o755)
    dest=DOC/(engine+'-'+geometry); dest.mkdir(parents=True,exist_ok=False)
    env=dict(BASE_ENV,REDIS74_ROOT=str(ROOT/'build/wave4/oracle'),
                 GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',
                 GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli',
                 GATE_DIFFER_ORACLE_CORES=oracle,GATE_LOAD_CORES=clients,
                 GATE_RUN_ID='wave4b-final-standard',GATE_DIFFER_GEOMETRY=geometry,
                 GATE_DIFFER_OUT=str(OUT/(engine+'-'+geometry)),GATE_TEST_PORT='26899',
                 WAVE4_FIXTURE_PORT_LOG=str(OUT/'fixture-ports.log'))
    argv=['taskset','-c',clients,'bash','tests/differ_gate.sh',str(wrapper),str(port),str(port+1),servers,'6:2']
    result=dict(argv=argv,env={k:v for k,v in env.items() if k.startswith(('GATE_','REDIS74','WAVE4','PYTHONPATH'))},
                    binary=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
    (dest/'command.json').write_text(json.dumps(result,indent=2)+'\n')
    start=time.monotonic()
    with (dest/'output.log').open('w') as stream:
        result['returncode']=subprocess.run(argv,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT).returncode
    result['seconds']=time.monotonic()-start
    (dest/'result.json').write_text(json.dumps(result,indent=2)+'\n')
    print(engine,geometry,result['returncode'],flush=True)
    return result


def engine_run(engine):
    allocation=('64-71','72','73-79',26860) if engine=='uring' else ('96-103','104','105-111',26862)
    return [matrix_run(engine,geometry,allocation) for geometry in ('split','armed-fused')]


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--label',default='differ')
    parser.add_argument('--parallel-matrices',action='store_true')
    args=parser.parse_args()
    assert '/' not in args.label and args.label not in ('.','..')
    OUT=ROOT/'build/wave4'/args.label;DOC=ROOT/'docs/wave4'/args.label
    OUT.mkdir(parents=True,exist_ok=True);DOC.mkdir(parents=True,exist_ok=True)
    BASE_ENV=run_proof.setup()
    if args.parallel_matrices:
        # Four disjoint groups: eight server CPUs, one oracle CPU, three client CPUs.
        specs=[]
        for index,(engine,geometry) in enumerate((('uring','split'),('epoll','split'),
                                                 ('uring','armed-fused'),('epoll','armed-fused'))):
            first=64+12*index
            specs.append((engine,geometry,(f'{first}-{first+7}',str(first+8),
                                          f'{first+9}-{first+11}',26860+2*index)))
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(lambda spec:matrix_run(*spec),specs))
    else:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=[r for group in pool.map(engine_run,('uring','epoll')) for r in group]
    (DOC/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    raise SystemExit(any(r['returncode'] for r in results))
