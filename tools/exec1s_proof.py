#!/usr/bin/env python3
"""Run the exec1s correctness inventory through the gate job interface only.
No full iteration, ABBA, rate measurement, or standalone load generator.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import re

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'build/exec1s-evidence/proof'
PORTS='20400-20499'
SERVER_CORES='48-55'
CLIENT_CORES='56-63'
# Existing families retain every internal mode/engine/atomic leg and assertion.
JOBS='''exec1s txnorder_index txnorder2 txnorder_wake txnorder-fused-0 txnorder-fused-1
 txnorder-split-0 txnorder-split-1 execfair debug-0 debug-1 fused-0 fused-1
 txn_group_fused txn_group_split atomfix5_watch atomfix5_accounting atomic_units
 atomic_batteries feature-split-0 feature-split-1 feature-armed-0 feature-armed-1
 script_bounds scriptfix lualibs sort auth authfix dump_restore blockfix_registry blockfix_structure blockfix_mkstream
 wait_units notify notifycompat notify_order notify_aof tracking_redirect trackfix_order trackfix_accounting
 flip fliplisten flipctl flip_unit flipfix_units moverfix lbplanner_units lb-stationary-1s lb-stationary-2s
 core_units splitlocal_units rlfix3_zc rlfix3_info rlcache rldbg ring_unit filter_unit hexpread
 climonfix clientfix racefix_counters racefix_climon storage_units perfex_units perfex_live ntnew4_live ntfix_input perfio_stream netio-1s netio-2s
 wb_rule_units wbland_units wb_policy iofix-deferred iofix-hz iofix-sleep iofix-signal
 aof-uring aof-epoll snapshot-uring snapshot-epoll aof_frame aoforder
 datafix2_watch datafix2_notouch bplus acl_recheck aclfix readonly serverfix_waitaof respcompat tls
 release_batteries compat2 compat3 exbatch_units exbatch_live
 reorder_sync reorder_engagement reorder_identity
 asan_batteries replyoff zc bugs5 netcmd_units persistfix_units'''.split()
JOBS += [f'multidb-{mode}-{rl}-{atomic}' for mode in ('1s','2s') for rl in (0,1) for atomic in (0,1)]
JOBS += [f'feature-cell-{mode}-{rl}-{cl}-{reorder}-{flip}' for mode in ('1s','2s')
         for rl in (0,1) for cl in (0,1) for reorder in (0,1) for flip in (0,1)]
JOBS += ['feature-cell-'+shape for shape in ('split-home-min','fused-home-max-nopin','split-shards-auto')]
JOBS += [f'respresume-{case}-{mode}-{engine}' for case in ('fragment','cpu','neighbour')
         for mode in ('1s','2s') for engine in ('uring','epoll')]
JOBS += [f'evict-{section}-{mode}-{atomic}' for section in ('lruclock','lfu')
         for mode in ('split','armed') for atomic in (0,1)]
MAINTAINER_JOBS = {'flip_saturated', 'atomic_floor', 'abba'}

def run(label,cmd,env=None):
    OUT.mkdir(parents=True,exist_ok=True)
    original=label
    attempt=1
    while (OUT/(label+'.log')).exists() or (OUT/(label+'.json')).exists():
        attempt+=1; label=original+'-attempt-'+str(attempt)
    receipt=OUT/(label+'.json')
    log=OUT/(label+'.log')
    if env is not None and 'GATE_LEDGER' in env:
        env=dict(env, GATE_LEDGER=str(OUT/(label+'.ledger')))
    binary=Path(cmd[cmd.index('--candidate-binary')+1]) if '--candidate-binary' in cmd else None
    def sha(path):
        with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
    before=sha(binary) if binary else None
    started=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with log.open('w') as stream:
        p=subprocess.run(cmd,cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT)
    row=dict(command=cmd,returncode=p.returncode,log=str(log),selected_jobs=(env or {}).get('GATE_ONLY_JOBS'))
    row.update(started_utc=started,ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        candidate_sha256=before,candidate_unchanged=(not binary or sha(binary)==before),
        proof_environment={k:v for k,v in (env or {}).items() if k in (
            'GATE_TXN_FUSED','GATE_TXN_ATOMIC','GATE_EXEC1S_WB','GATE_DIFFER_NET_IO','GATE_PROOF_NO_RATES','LD_PRELOAD')})
    found=re.search(r'^  artifacts: (.+)$',log.read_text(),re.M)
    if found:row['artifacts']=found[1]
    if env and env.get('EXEC1S_CQ_WATCH')=='1':
        observations=[]
        if found:
            for path in Path(found[1]).rglob('*'):
                if path.is_file() and (path.name.endswith('.log') or 'srv' in path.name):
                    for line in path.read_text(errors='replace').splitlines():
                        if line.startswith('EXEC1S_CQ '):
                            observations.append(dict(log=str(path),**json.loads(line[len('EXEC1S_CQ '):])))
        row['cq_observations']=dict(instrument=env['LD_PRELOAD'],instrument_sha256=sha(Path(env['LD_PRELOAD'])),
            ring_rows=len(observations),samples=sum(x['samples'] for x in observations),
            fused_ex_ring_rows=sum(x['taskrun_flag'] for x in observations),
            overflow_samples=sum(x['overflow_samples'] for x in observations),
            dropped=sum(x['dropped'] for x in observations),
            passed=bool(observations) and all(x['deferred'] and not x['overflow_samples'] and not x['dropped'] for x in observations),
            observations=observations)
        if env.get('GATE_TXN_FUSED')=='1':
            row['cq_observations']['passed'] &= row['cq_observations']['fused_ex_ring_rows']>0
    row['success']=p.returncode==0 and row['candidate_unchanged'] and row.get('cq_observations',{}).get('passed',True)
    receipt.write_text(json.dumps(row,indent=2)+'\n')
    print(label,'PASS' if row['success'] else 'FAIL',p.returncode,flush=True)
    return row['success']

def gate(label,binary,jobs,engine='uring',extra_env=None):
    assert not (set(jobs) & MAINTAINER_JOBS), 'load-generator/rate jobs belong to the maintainer'
    env=os.environ.copy()
    env.update(GATE_ONLY_JOBS=' '.join(jobs),GATE_DIFFER_NET_IO=engine,
               GATE_PROOF_NO_RATES='1',
               REDIS74_ROOT='/home/user/Projects/redis',
               GATE_LEDGER=str(OUT/(label+'.ledger')))
    if extra_env: env.update(extra_env)
    return run(label,['taskset','-c','48-63','tests/gate.sh','iteration',
        '--server-cores',SERVER_CORES,'--load-cores',CLIENT_CORES,
        '--server-smt','','--load-smt','','--ports',PORTS,
        '--candidate-binary',str(binary)],env)

def main():
    global PORTS,SERVER_CORES,CLIENT_CORES
    p=argparse.ArgumentParser()
    p.add_argument('--families',action='store_true')
    p.add_argument('--ports',default=PORTS)
    p.add_argument('--server-cores',default=SERVER_CORES)
    p.add_argument('--client-cores',default=CLIENT_CORES)
    p.add_argument('--differ-arms',default='')
    p.add_argument('--engines',default='uring,epoll')
    p.add_argument('--self-test',action='store_true')
    p.add_argument('--jobs',default='')
    p.add_argument('--label',default='POST-additional')
    p.add_argument('--candidate',default='build/tomokv')
    p.add_argument('--txn-fused',action='store_true')
    p.add_argument('--txn-atomic',choices=['0','1'],default='1')
    p.add_argument('--wb',action='store_true')
    p.add_argument('--cq-watch',action='store_true',help='correctness-only liburing boundary observer; use with AOF jobs')
    a=p.parse_args();PORTS=a.ports;SERVER_CORES=a.server_cores;CLIENT_CORES=a.client_cores
    low,high=map(int,PORTS.split('-'));assert 20400<=low<=high<=20499
    assert os.sched_getaffinity(0) <= set(range(48,64)), 'start under taskset -c 48-63'
    def cpus(spec):
        values=set()
        for part in spec.split(','):
            span=list(map(int,part.split('-')))
            assert len(span) in (1,2)
            values.update(range(span[0],span[-1]+1))
        return values
    server_cpus,client_cpus=cpus(SERVER_CORES),cpus(CLIENT_CORES)
    assert len(server_cpus)==8 and client_cpus and not (server_cpus & client_cpus)
    assert (server_cpus | client_cpus) <= set(range(48,64))
    passed=True
    extra={'GATE_TXN_FUSED':str(int(a.txn_fused)), 'GATE_TXN_ATOMIC':a.txn_atomic,
           'GATE_EXEC1S_WB':str(int(a.wb))}
    if a.cq_watch:
        instrument=ROOT/'build/exec1s-cq-watch.so';assert instrument.exists()
        extra.update(LD_PRELOAD=str(instrument),EXEC1S_CQ_WATCH='1')
    if a.jobs:
        passed=gate(a.label,(ROOT/a.candidate).resolve(),a.jobs.split(','),extra_env=extra) and passed
    if a.families:
        passed=gate('POST-families',(ROOT/a.candidate).resolve(),JOBS,extra_env=extra) and passed
    for arm in filter(None,a.differ_arms.split(',')):
        for engine in a.engines.split(','):
            assert engine in ('uring','epoll')
            # Collect each arm's finite transaction-order witnesses once. The
            # execfair job itself covers both engines, modes and namespaces.
            jobs=['differ-split','differ-armed']
            if engine=='uring':jobs.append('execfair')
            passed=gate(arm+'-differ-'+engine,ROOT/'build'/('exec1s-'+arm),
                        jobs,engine) and passed
    if a.self_test:
        passed=run('gates-test',['taskset','-c','48-63','python3','tests/gates_test.py']) and passed
    raise SystemExit(0 if passed else 1)
if __name__=='__main__':main()
