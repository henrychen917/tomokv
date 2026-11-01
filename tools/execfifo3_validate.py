#!/usr/bin/env python3
"""execfifo2's complete job groups, pinned to execfifo3's allocation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from execfifo2_validate import GROUPS

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/execfifo3/validation'
DOCS=ROOT/'docs/execfifo3/validation'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('groups',nargs='+',choices=sorted(GROUPS));a=p.parse_args()
    assert os.sched_getaffinity(0)<=set(range(96,112))
    OUT.mkdir(parents=True,exist_ok=True);DOCS.mkdir(parents=True,exist_ok=True)
    manifest=DOCS/'runs.json';rows=json.loads(manifest.read_text()) if manifest.exists() else []
    failures=0
    for name in a.groups:
        tier,jobs,extra=GROUPS[name]
        env=dict(os.environ,LC_ALL='C',GATE_PROOF_NO_RATES='1',GATE_ONLY_JOBS=jobs,
                 REDIS74_ROOT='/home/user/Projects/redis',
                 GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis/src/redis-server',
                 GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis/src/redis-cli',**extra)
        log=OUT/(name+'-'+str(time.time_ns())+'.log')
        cmd=['tests/gate.sh',tier,'--server-cores','96-103','--server-smt','',
             '--load-cores','104-111','--load-smt','','--ports','20600-20699']
        row=dict(group=name,command=cmd,environment={k:env[k] for k in env if k in extra or k.startswith('GATE_') or k in ('LC_ALL','REDIS74_ROOT')},
                 binary_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest(),log=str(log))
        print('START',name,flush=True)
        with log.open('w') as stream:result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
        text=log.read_text();match=re.search(r'  artifacts: (.*)',text)
        row.update(exit_code=result.returncode,run_directory=match[1] if match else None)
        rows.append(row);manifest.write_text(json.dumps(rows,indent=2)+'\n')
        failures+=result.returncode!=0
        print('DONE',name,result.returncode,text.splitlines()[-1] if text else 'empty log',flush=True)
    return int(failures!=0)

if __name__=='__main__':raise SystemExit(main())
