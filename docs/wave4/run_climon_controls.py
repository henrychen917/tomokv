#!/usr/bin/env python3
"""Bounded, unchanged climon/seed-19 controls on fresh headline and POST boots."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import run_supplemental as support

ROOT=support.ROOT
OUT=ROOT/'build/wave4/climon-controls'
DOC=ROOT/'docs/wave4/climon-controls'


def arm(name,binary,allocation):
    servers,oracle,clients,port=allocation
    rows=[]
    for roll in range(1,4):
        label=f'{name}-{roll}'
        shape=['--shards','16','--thread-mode','fused','--read-local','1',
               '--net-io','epoll','--databases','16','--atomic','0']
        with support.owned(label+'-oracle',Path('/home/user/Projects/redis74/src/redis-server'),
                           oracle,port+1,[]):
            with support.owned(label+'-target',binary,servers,port,shape):
                argv=['taskset','-c',clients,'python3','tests/differ.py',
                      '127.0.0.1',str(port),'127.0.0.1',str(port+1),'climon','19']
                env=dict(os.environ,PYTHONPATH=str(DOC.parent/'fixture_site'),
                         WAVE4_FIXTURE_PORT_LOG=str(OUT/'fixture-ports.log'))
                with (DOC/(label+'.log')).open('w') as log:
                    rc=subprocess.run(argv,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
                rows.append(dict(roll=roll,argv=argv,returncode=rc))
        print(label,rc,flush=True)
    result=dict(binary=str(binary),sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                allocation=allocation,rows=rows)
    (DOC/(name+'.json')).write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=False);DOC.mkdir(parents=True,exist_ok=False)
    support.OUT=OUT
    specs=[('headline',Path('/home/user/Projects/bench-bins/tomokv-headline-8656f9fa9'),
            ('64-71','72','73-75',26860)),
           ('post',ROOT/'build/tomokv',('76-83','84','85-87',26862))]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda spec:arm(*spec),specs))
    (DOC/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    raise SystemExit(any(row['returncode'] for result in results for row in result['rows']))
