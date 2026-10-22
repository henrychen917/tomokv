#!/usr/bin/env python3
"""Run only gate.sh's selected correctness jobs and retain their real ledgers."""
import argparse, gzip, hashlib, json, os, re, shutil, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'docs/compat2b'
POST_JOBS="""config_unit flip_unit filter_unit ring_unit storage_units
core_units flipfix_units persistfix_units perfex_units lbplanner_units exbatch_units
wb_rule_units wbland_units splitlocal_units atomic_units netcmd_units wait_units
reorder_sync reorder_engagement reorder_identity acl_metadata cmd_metadata
compat2 tls ntfix_input netcap respcompat netio-1s netio-2s abba_selftest""".split()
p=argparse.ArgumentParser(); p.add_argument('arm',choices=['pre','post']); p.add_argument('--jobs',default=''); p.add_argument('--label',default=''); a=p.parse_args()
cwd=ROOT if a.arm=='post' else ROOT/'build/compat2b/headline-src'
binary=cwd/'build/tomokv'; target=OUT/('gate-'+a.arm+a.label); target.mkdir(parents=True,exist_ok=False)
# Redis source lives beside the pinned binary-only oracle. No oracle files are modified.
oracle=ROOT/'build/compat2b/oracle'; (oracle/'src').mkdir(parents=True,exist_ok=True)
for source in Path('/home/user/Projects/redis/src').iterdir():
 dest=oracle/'src'/source.name
 if not dest.exists(): dest.symlink_to(source)
for name in ['redis-server','redis-cli']:
 dest=oracle/'src'/name
 if dest.is_symlink(): dest.unlink()
 dest.symlink_to(Path('/home/user/Projects/redis74/src')/name)
jobs=a.jobs.split() if a.jobs else (['compat2'] if a.arm=='pre' else POST_JOBS)
env=dict(os.environ,REDIS74_ROOT=str(oracle),GATE_ONLY_JOBS=' '.join(jobs),
 GATE_DIFFER_ORACLE_CORES='72',GATE_TEST_PORT='26899',
 GATE_HISTORY=str(ROOT/'build/compat2b'/('history-'+target.name)),
 GATE_LEDGER=str(target/'ledger'),TMPDIR=str(ROOT/'build/compat2b/tmp'))
Path(env['TMPDIR']).mkdir(parents=True,exist_ok=True)
argv=['taskset','-c','64-79','bash','tests/gate.sh','quick','--server-cores','64-72',
 '--load-cores','73-79','--server-smt','','--load-smt','','--ports','26800-26899',
 '--candidate-binary',str(binary)]
receipt=dict(argv=argv,cwd=str(cwd),env={k:env[k] for k in env if k.startswith(('GATE_','REDIS74','TMPDIR'))},
 binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest())
(target/'command.json').write_text(json.dumps(receipt,indent=2)+'\n')
with (target/'gate.log').open('w') as log: rc=subprocess.run(argv,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
receipt['returncode']=rc
m=re.search(r'artifacts: (\S+)',(target/'gate.log').read_text())
if m:
 run=Path(m[1]); receipt['run_directory']=str(run)
 for source in run.rglob('*'):
  if not source.is_file() or source.is_symlink(): continue
  with source.open('rb') as stream: magic=stream.read(4)
  if magic==b'\x7fELF' or source.suffix in ('.o','.a'): continue
  dest=target/'run'/source.relative_to(run); dest.parent.mkdir(parents=True,exist_ok=True)
  if source.stat().st_size>131072:
   with source.open('rb') as inp,gzip.open(str(dest)+'.gz','wb') as out: shutil.copyfileobj(inp,out)
  else: shutil.copy2(source,dest)
(target/'result.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(target,rc,flush=True)
raise SystemExit(rc)
