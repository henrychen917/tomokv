#!/usr/bin/env python3
"""Lane CPU/port-bound partial gate invocations; no full iteration or load generators."""
import argparse, json, os, subprocess
from pathlib import Path
import exec1sd as d
import exec1s_proof as inherited

def gate(label, jobs, engine='uring', extra=None, candidate=None, ports='20010-20097', server_cores='64-87', load_cores='88-95'):
    inherited.OUT = d.OUT/'proof'
    env = dict(os.environ, GATE_ONLY_JOBS=' '.join(jobs), GATE_DIFFER_NET_IO=engine,
               GATE_PROOF_NO_RATES='1', GATE_TEST_PORT='20098',
               REDIS74_ROOT='/home/user/Projects/redis',
               GATE_LEDGER=str(inherited.OUT/(label+'.ledger')))
    if extra: env.update(extra)
    return inherited.run(label, ['taskset','-c',d.CPUS,'tests/gate.sh','iteration',
        '--server-cores',server_cores,'--load-cores',load_cores,'--server-smt','','--load-smt','',
        '--ports',ports,'--candidate-binary',str(candidate or d.ROOT/'build/tomokv')],env)

def main():
    assert os.sched_getaffinity(0)<=set(range(64,96))
    p=argparse.ArgumentParser()
    p.add_argument('phase',choices=['core','families','supplement','differ','harness','lottery'])
    a=p.parse_args();out=[]
    if a.phase=='core':
        out.append(gate('core',['exec1s','txnorder_wound','at412-owner','txnorder_index']+
            [f'multifix-{mode}-{engine}' for mode in ('1s','2s') for engine in ('uring','epoll')]))
    elif a.phase=='families':
        jobs=list(dict.fromkeys(inherited.JOBS+['txnorder_wound',
            'blockfix2','streamfix','crlffix','persistfix2_lastsave',
            'persistfix2_shutdown','persistfix2_commands','persistfix2_errors',
            'wb_mixed','slotless','reorder_bounds','rob_portable']))
        # Expand at412's registered stage-specific jobs rather than choosing one stage.
        gate_text=(d.ROOT/'tests/gate.sh').read_text()
        import re
        # Names are owned by plan_jobs and inspected before invocation.
        jobs += ['at412-'+name for name in (
            'T1','T2','T3','T4','T5','T6','T7','T8','T9','T10','T11a','T11b',
            'T12','T13','T14','T15','T16','owner')]
        jobs += [f'multifix-{mode}-{engine}' for mode in ('1s','2s') for engine in ('uring','epoll')]
        out.append(gate('families',jobs))
    elif a.phase=='supplement':
        fused='release_batteries atomic_batteries sort debug-0 debug-1 script_bounds dump_restore auth snapshot-uring snapshot-epoll notify aof-uring aof-epoll aof_frame asan_batteries replyoff'.split()
        out.append(gate('fused-legs',fused,extra={'GATE_TXN_FUSED':'1','GATE_TXN_ATOMIC':'1'}))
        for mode in ('0','1'):
            out.append(gate('script-a0-'+mode,['script_bounds'],extra={'GATE_TXN_FUSED':mode,'GATE_TXN_ATOMIC':'0'}))
    elif a.phase=='differ':
        for engine in ('uring','epoll'):
            out.append(gate('differ-'+engine,['differ-split','differ-armed'],engine))
    elif a.phase=='lottery':
        binary=d.ROOT/'build/lottery/tomokv'
        subprocess.run(['make','-q','build/lottery/tomokv'],check=True)
        d.save(d.DOCS/'lottery-build.json',dict(binary=str(binary),sha256=d.sha(binary),
            production_sha256=d.sha(d.ROOT/'build/tomokv'),
            copy_patches_sha256=d.sha(d.ROOT/'build/lottery/source/lottery-patches.json'),
            build_log_sha256=d.sha(d.OUT/'evidence/lottery-final-build.log')))
        out.append(gate('lottery-copy-smoke',['execfair'],candidate=binary,ports='20002-20009',server_cores='64-71',load_cores='72-95'))
    else:
        env=dict(os.environ,GATE_TEST_PORT='20098')
        inherited.OUT=d.OUT/'proof'
        out.append(inherited.run('gates-test',['taskset','-c',d.CPUS,'python3','tests/gates_test.py'],env))
    d.save(d.DOCS/(a.phase+'-invocations.json'),dict(passed=all(out),results=out))
    raise SystemExit(0 if all(out) else 1)

if __name__=='__main__':main()
