#!/usr/bin/env python3
"""Invoke only gate.sh's whole-job interface, retain every exit and run directory."""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('name');p.add_argument('jobs',nargs='+')
p.add_argument('--engine',choices=('uring','epoll'),default='uring')
p.add_argument('--fused',action='store_true');p.add_argument('--binary',default='build/tomokv')
p.add_argument('--port',type=int,default=20301);p.add_argument('--asan-binary',type=Path)
a=p.parse_args();assert 20300<=a.port<=20389
server_cores='32-45';load_cores='46-47';os.sched_setaffinity(0,set(range(32,48)))
output=ROOT/'docs/rlfix4/jobs';output.mkdir(parents=True,exist_ok=True)
log=output/(a.name+'.log'); assert not log.exists(), 'preserve the earlier attempt'
binary=(ROOT/a.binary).resolve()
env=dict(os.environ,LANG='en_US.UTF-8',REDIS74_ROOT='/home/user/Projects/redis',
    GATE_ONLY_JOBS=' '.join(a.jobs),GATE_NET_IO=a.engine,GATE_PROOF_NET_IO=a.engine,
    GATE_ZC_NET_IO=a.engine,GATE_SHUTDOWN_NET_IO=a.engine,GATE_DIFFER_NET_IO=a.engine,
    GATE_TXN_FUSED=str(int(a.fused)),GATE_TEST_PORT='20397',GATE_PROOF_NO_RATES='1',
    GATE_LEDGER=str(output/(a.name+'.tsv')))
env.pop('LC_ALL',None)
if a.asan_binary is not None:
    env['GATE_ASAN_BINARY'] = str(a.asan_binary.resolve())
argv=['bash','tests/gate.sh','full','--server-cores',server_cores,
    '--load-cores',load_cores,'--load-smt','',
    '--ports',f'{a.port}-{a.port+9}','--candidate-binary',str(binary)]
receipt=dict(argv=argv,cwd=str(ROOT),env={k:v for k,v in env.items() if k.startswith('GATE_') or k in ('LANG','REDIS74_ROOT')},
    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    gate_sha256=hashlib.sha256((ROOT/'tests/gate.sh').read_bytes()).hexdigest(),started=time.time())
with log.open('w') as f:
    result=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
receipt.update(exit=result.returncode,seconds=time.time()-receipt['started'])
text=log.read_text();match=re.search(r'  artifacts: (.+)',text)
if match:receipt['artifacts']=match[1]
receipt['summary']=[line for line in text.splitlines() if line.startswith('GATE(PARTIAL)')]
receipt['binary_unchanged']=receipt['binary_sha256']==hashlib.sha256(binary.read_bytes()).hexdigest()
(output/(a.name+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
raise SystemExit(result.returncode)
