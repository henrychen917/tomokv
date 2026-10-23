#!/usr/bin/env python3
"""Correctness-only gate job selector; never full iteration or performance rows."""
import argparse,hashlib,json,os,re,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];DOC=ROOT/'docs/wave5';BUILD=ROOT/'build/wave5'
p=argparse.ArgumentParser();p.add_argument('name');p.add_argument('jobs');p.add_argument('--engine',choices=['uring','epoll']);p.add_argument('--mode',choices=['1s','2s']);p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--single-slot',action='store_true');a=p.parse_args()
assert a.jobs and not set(a.jobs.split())&{'atomic_floor','efficiency'},'performance jobs remain with maintainer'
OUT=DOC/'gate'/a.name;OUT.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,REDIS74_ROOT='/home/user/Projects/redis',GATE_DIFFER_ORACLE_BIN='/home/user/Projects/redis74/src/redis-server',GATE_DIFFER_REDIS_CLI='/home/user/Projects/redis74/src/redis-cli',GATE_DIFFER_ORACLE_CORES='95',GATE_GLOBCASE_ORACLE_CORES='95',GATE_TEST_PORT='26899',GATE_DIFFER_HISTORY=str(BUILD/'differ-history'),GATE_HISTORY=str(BUILD/'gate-history'),PYTHONPATH=str(DOC/'port_guard')+os.pathsep+os.environ.get('PYTHONPATH',''),WAVE5_PORT_RECEIPT=str(DOC/'fixture-ports.jsonl'),GATE_ONLY_JOBS=a.jobs,GATE_LEDGER=str(OUT/'ledger'))
tls_oracle=BUILD/'redis74-tls/src/redis-server'
if tls_oracle.exists():env['NETFIX_TLS_ORACLE']=str(tls_oracle)
source_binary=a.root/'build/tomokv'
digest=hashlib.sha256(source_binary.read_bytes()).hexdigest()
snapshot=BUILD/'gate-binaries'/digest;snapshot.mkdir(parents=True,exist_ok=True)
binary=snapshot/'tomokv'
if not binary.exists():shutil.copy2(source_binary,binary)
for unit in (ROOT/'build').glob('*'):
 if unit.is_file() and os.access(unit,os.X_OK) and unit.name!='tomokv' and not (snapshot/unit.name).exists():(snapshot/unit.name).symlink_to(unit)
env['WAVE5_BINARY']=str(binary)
if a.engine or a.mode:
 binary=DOC/'server_adapter.py'
 if a.engine:env['WAVE5_ENGINE']=a.engine
 if a.mode:env['WAVE5_MODE']=a.mode
 env['WAVE5_LAUNCH_DIR']=str(OUT/'launches')
cmd=['taskset','-c','64-95',str(a.root/'tests/gate.sh'),'full','--server-cores','64-71' if a.single_slot else '64-79','--load-cores','72-95' if a.single_slot else '80-95','--load-smt','','--ports','26800-26889','--candidate-binary',str(binary)]
row=dict(command=cmd,jobs=a.jobs.split(),started=time.time(),binary_sha256=digest,snapshot_binary=str(snapshot/'tomokv'),environment={k:v for k,v in env.items() if k.startswith(('GATE_','WAVE5_','REDIS74_ROOT','PYTHONPATH','NETFIX_TLS_ORACLE'))})
with (OUT/'gate.log').open('w') as f:row['returncode']=subprocess.run(cmd,cwd=a.root,env=env,stdout=f,stderr=subprocess.STDOUT).returncode
row['elapsed']=time.time()-row['started']
text=(OUT/'gate.log').read_text();runs=re.findall(r'(?:/[^\s;]+/)?build/gate-run\.[A-Za-z0-9]+',text);row['run_paths']=list(dict.fromkeys(runs))
row['binary_stable']=row['binary_sha256']==hashlib.sha256((snapshot/'tomokv').read_bytes()).hexdigest()
(OUT/'result.json').write_text(json.dumps(row,indent=2)+'\n');print(json.dumps(row),flush=True)
raise SystemExit(row['returncode'])
