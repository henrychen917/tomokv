#!/usr/bin/env python3
"""Invoke only gate.sh's whole-job interface, retain every exit and run directory."""
import argparse, hashlib, json, os, re, subprocess, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser()
p.add_argument('name'); p.add_argument('jobs', nargs='+')
p.add_argument('--engine', choices=('uring','epoll'), default='uring')
p.add_argument('--fused', action='store_true'); p.add_argument('--single-slot', action='store_true')
p.add_argument('--binary', default='build/tomokv'); p.add_argument('--root', type=Path, default=ROOT)
p.add_argument('--port', type=int, default=20020)
p.add_argument('--server-start', type=int, choices=(64,72,80,88))
p.add_argument('--asan-binary', type=Path)
a=p.parse_args()
assert 20000 <= a.port <= 20080
if a.server_start is not None:
    assert a.single_slot
server_cores = ('64-71' if a.single_slot else '64-87') if a.server_start is None else f'{a.server_start}-{a.server_start+7}'
load_cores = ('72-95' if a.single_slot else '88-95') if a.server_start is None else ','.join(
    str(c) for c in range(64,96) if not a.server_start <= c <= a.server_start+7)
os.sched_setaffinity(0, set(range(64,96)))
output=ROOT/'docs/wave8/jobs';output.mkdir(parents=True,exist_ok=True)
log=output/(a.name+'.log'); assert not log.exists(), 'preserve the earlier attempt'
binary=(ROOT/a.binary).resolve()
env=dict(os.environ,LANG='en_US.UTF-8',REDIS74_ROOT='/home/user/Projects/redis',
    GATE_ONLY_JOBS=' '.join(a.jobs),GATE_NET_IO=a.engine,GATE_PROOF_NET_IO=a.engine,
    GATE_ZC_NET_IO=a.engine,GATE_SHUTDOWN_NET_IO=a.engine,GATE_DIFFER_NET_IO=a.engine,
    GATE_TXN_FUSED=str(int(a.fused)),GATE_TEST_PORT='20098',
    GATE_LEDGER=str(output/(a.name+'.tsv')))
env.pop('LC_ALL',None)
if a.asan_binary is not None:
    env['GATE_ASAN_BINARY'] = str(a.asan_binary.resolve())
argv=['bash','tests/gate.sh','full','--server-cores',server_cores,
    '--load-cores',load_cores,'--load-smt','',
    '--ports',f'{a.port}-{a.port+9}','--candidate-binary',str(binary)]
receipt=dict(argv=argv,cwd=str(a.root),env={k:v for k,v in env.items() if k.startswith('GATE_') or k in ('LANG','REDIS74_ROOT')},
    binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
    gate_sha256=hashlib.sha256((a.root/'tests/gate.sh').read_bytes()).hexdigest(),started=time.time())
with log.open('w') as f:
    result=subprocess.run(argv,cwd=a.root,env=env,stdout=f,stderr=subprocess.STDOUT)
receipt.update(exit=result.returncode,seconds=time.time()-receipt['started'])
text=log.read_text();match=re.search(r'  artifacts: (.+)',text)
if match:receipt['artifacts']=match[1]
receipt['summary']=[line for line in text.splitlines() if line.startswith('GATE(PARTIAL)')]
receipt['binary_unchanged']=receipt['binary_sha256']==hashlib.sha256(binary.read_bytes()).hexdigest()
(output/(a.name+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps(receipt),flush=True)
raise SystemExit(result.returncode)
