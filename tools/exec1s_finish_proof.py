#!/usr/bin/env python3
"""POST correctness jobs and their supplementary legs; never a complete gate."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import exec1s_proof as proof

ROOT=Path(__file__).resolve().parents[1]
DOCS=ROOT/'docs/exec1s'

def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def freshness():
    body=(ROOT/'tests/gate.sh').read_text().split('job_production_units(){',1)[1].split('\n}',1)[0]
    first=body.split('>"$TMPDIR/build.log"',1)[0]
    targets=re.findall(r'build/[a-z0-9-]+',first)
    assert len(targets)==len(set(targets)) and len(targets)>40
    checks=[['make','-q','all']]+[['make','-q',t] for t in targets]
    for arm,flag in [('park',''),('no-wake',' -DTOMO_MDBQSBR_NO_WAKE')]:
        checks.append(['make','-q','BUILD_ROOT=build/mdbqsbr2-'+arm,
                       'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread -DTOMO_MDBQSBR_LIVE_PARK'+flag,'all'])
    checks.append(['make','-f','Makefile','-f','tools/blockfix_cost.mk','-q',
                   'build/blockfix-cost','build/tomokv.blockfix-cost.sha256'])
    rows=[]
    for cmd in checks:
        p=subprocess.run(cmd,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        rows.append(dict(command=cmd,returncode=p.returncode,output=p.stdout))
    record=dict(production_sha256=sha(ROOT/'build/tomokv'),targets=targets,checks=rows,
                passed=all(r['returncode']==0 for r in rows))
    (DOCS/'freshness.json').write_text(json.dumps(record,indent=2)+'\n')
    return record['passed']

def main():
    assert os.sched_getaffinity(0)<=set(range(48,64))
    candidate=ROOT/'build/exec1s-POST'
    outcomes=[]
    # Keep one eight-core server slot, with its own eight load CPUs. No builds
    # or debugger traces run beside live correctness jobs in this driver.
    outcomes.append(proof.gate('POST-families',candidate,proof.JOBS))
    fused='release_batteries atomic_batteries sort debug-0 debug-1 script_bounds dump_restore auth snapshot-uring snapshot-epoll notify aof-uring aof-epoll aof_frame asan_batteries replyoff'.split()
    outcomes.append(proof.gate('POST-fused-legs',candidate,fused,extra_env={'GATE_TXN_FUSED':'1','GATE_TXN_ATOMIC':'1'}))
    for fused_mode in ('0','1'):
        outcomes.append(proof.gate('POST-script-a0-'+fused_mode,candidate,['script_bounds'],
                                   extra_env={'GATE_TXN_FUSED':fused_mode,'GATE_TXN_ATOMIC':'0'}))
    for engine in ('uring','epoll'):
        outcomes.append(proof.gate('POST-differ-'+engine,candidate,['differ-split','differ-armed'],engine))
    instrument=ROOT/'build/exec1s-cq-watch.so'
    subprocess.run(['g++','-std=c++20','-O2','-g','-shared','-fPIC','tests/exec1s_cq_watch.cc','-o',str(instrument),'-ldl'],cwd=ROOT,check=True)
    for fused_mode in ('0','1'):
        outcomes.append(proof.gate('POST-aof-cq-'+fused_mode,candidate,['aof-uring','aof_frame'],extra_env={
            'GATE_TXN_FUSED':fused_mode,'LD_PRELOAD':str(instrument),'EXEC1S_CQ_WATCH':'1'}))
    outcomes.append(proof.run('gates-test',['taskset','-c','48-63','python3','tests/gates_test.py']))
    outcomes.append(freshness())
    receipts=[json.loads(p.read_text())|dict(receipt=str(p)) for p in sorted(proof.OUT.glob('*.json'))]
    summary=dict(production_binary=str(candidate),production_sha256=sha(candidate),receipts=receipts,
                 passed=all(outcomes),not_run=[
                     dict(job='flip_saturated',reason='Invokes memtier; performance/load generators reserved for maintainer.'),
                     dict(job='atomic_floor',reason='Invokes memtier; performance/load generators reserved for maintainer.'),
                     dict(job='atomic_ryow rate assertion',reason='GATE_PROOF_NO_RATES=1; finite correctness schedules retained.'),
                     dict(job='full gate iteration / performance merit',reason='Reserved for maintainer.')])
    (DOCS/'live-proof.json').write_text(json.dumps(summary,indent=2)+'\n')
    raise SystemExit(0 if all(outcomes) else 1)

if __name__=='__main__':main()
