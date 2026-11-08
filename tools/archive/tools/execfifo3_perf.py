#!/usr/bin/env python3
"""perf stat on bounded serverless fixtures, no servers or throughput output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/execfifo3/perf'
# On this kernel cache-misses aliases combined instruction/data L2 misses,
# not LLC misses. See docs/execfifo3/pmu-audit for availability probes.
EVENTS=[['instructions:u','cycles:u','L1-dcache-load-misses:u'],
        ['l2_cache_req_stat.ls_rd_blk_c:u','cache-misses:u','ls_any_fills_from_sys.remote_cache:u'],
        ['ls_any_fills_from_sys.local_ccx:u','l2_request_g1.change_to_x:u','ic_tag_hit_miss.instruction_cache_miss:u']]
CELLS=[(cmd,mode,local,threads) for cmd,mode,local in
       [('SET','1s',0),('SET','1s',1),('INCR','1s',0),('INCR','1s',1),('SET','2s',0)]
       for threads in (1,2)]
CELLS += [(cmd,'1s',local,1) for cmd in ('PARSE-SET','PARSE-INCR') for local in (0,1)]

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--arms',default='PRE,FIFO,POST-final')
    p.add_argument('--blocks',type=int,default=3);p.add_argument('--turns',type=int,default=8192)
    a=p.parse_args();assert os.sched_getaffinity(0)<=set(range(96,112))
    OUT.mkdir(parents=True,exist_ok=True);rows=[]
    for block in range(a.blocks):
        arms=a.arms.split(',')
        if block%2:arms.reverse()
        for command,mode,local,threads in CELLS:
            for arm in arms:
                binary=ROOT/'build/execfifo3/memory-scopes'/(arm+'-db0')/'probe'
                for group,events in enumerate(EVENTS):
                    label=f'{block}-{arm}-{command}-{mode}-l{local}-t{threads}-e{group}'
                    stats=OUT/(label+'.csv');log=OUT/(label+'.log')
                    cmd=['perf','stat','-x,','-o',str(stats),'-e',','.join(events),'--',str(binary),command,mode,'32','1',str(local)]
                    env=dict(os.environ,LC_ALL='C',EXECFIFO3_THREADS=str(threads),EXECFIFO3_TURNS=str(a.turns))
                    with log.open('w') as stream:r=subprocess.run(cmd,env=env,stdout=stream,stderr=subprocess.STDOUT)
                    text=stats.read_text();passed=r.returncode==0 and 'PASS finite' in log.read_text() and '<not ' not in text
                    values={}
                    for line in text.splitlines():
                        fields=line.split(',')
                        if len(fields)>3 and fields[2] in events:
                            values[fields[2]]=dict(count=fields[0],runtime_ns=fields[3],running_percent=fields[4] if len(fields)>4 else None)
                    passed &= len(values)==len(events)
                    rows.append(dict(block=block,arm=arm,command=command,mode=mode,read_local=local,threads=threads,
                        turns=a.turns,batch=32,events=events,values=values,invocation=cmd,returncode=r.returncode,passed=passed,
                        probe_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),csv=str(stats),log=str(log)))
                    (OUT/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
                    print(label,'PASS' if passed else 'FAIL',flush=True)
                    assert passed,label
    print('PASS',len(rows),'finite counter runs; counts include fixture preparation and checks, no rates')

if __name__=='__main__':main()
