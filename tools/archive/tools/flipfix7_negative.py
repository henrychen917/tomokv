#!/usr/bin/env python3
"""Strict PRE gate rejection and PAD-A liveness witnesses; correctness only."""
import argparse,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser();p.add_argument('arm',choices=('PRE','PAD-A'));args=p.parse_args()
 out=ROOT/'build/flipfix7';env=dict(os.environ,LC_ALL='C',GATE_TEST_PORT='21097',PARBUILD_JOBS='13',GATE_PROOF_NO_RATES='1')
 if args.arm=='PRE':
  env['GATE_ONLY_JOBS']='flipfix7_output flipfix7_blocked flipfix7_tls'
  cmd=['taskset','-c','48-60','tests/gate.sh','quick','--server-cores','48-55','--load-cores','56-60','--ports','21000-21099','--candidate-binary',str(out/'PRE')]
  with (out/'gate-negative-pre.log').open('w') as f:r=subprocess.run(cmd,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
  assert r.returncode==1,r.returncode
  # The ledger must reject all three semantic rows; missing job / boot failure is not a witness.
  import re
  run=Path(re.search(r'artifacts: (.+)',(out/'gate-negative-pre.log').read_text())[1])
  states={job:(run/'jobs'/job/'done').read_text().split() for job in ('flipfix7_output','flipfix7_blocked','flipfix7_tls')}
  assert all(v==['0','0','1'] for v in states.values()),states
  for job in states:
   snapshots=list((run/'jobs'/job).rglob('snapshot.json'))
   assert snapshots,(job,'never reached a held production stage')
  print('PASS negative PRE: all three live rows reject a witnessed held FLIP',flush=True)
 else:
  results=[]
  for db in (1,16):
   folder=out/f'pad-a-d{db}'
   cmd=['taskset','-c','56-60','python3','tests/flipfix7.py','--binary',str(out/'PAD-A'),'--cores','48-55','--port','21000','--output',str(folder),'--arm','pre','--cases','blocked,tls,late','--engines','uring,epoll','--atomics','0','--databases',str(db),'--read-local','0']
   with (out/f'pad-a-d{db}.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
   results+=json.loads((folder/'summary.json').read_text())
  (ROOT/'docs/flipfix7/pad-a-witnesses.json').write_text(json.dumps(results,indent=2)+'\n')
  print('PASS PAD-A witnesses',len(results),flush=True)
if __name__=='__main__':main()
