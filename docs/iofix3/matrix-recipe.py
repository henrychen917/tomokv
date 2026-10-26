import json
import os
from pathlib import Path
import subprocess
import time

root = Path('/home/user/Projects/cx-iofix3')
os.chdir(root)
doc = root/'docs/iofix3'

def gate(name, jobs, arm='post2', engine='uring', fused=False, expected=0):
    env = dict(os.environ, GATE_ONLY_JOBS=jobs, GATE_NET_IO=engine,
               GATE_ZC_NET_IO=engine, GATE_SHUTDOWN_NET_IO=engine,
               GATE_DIFFER_NET_IO=engine, GATE_TXN_FUSED=str(int(fused)),
               GATE_TEST_PORT='48898')
    argv = ['tests/gate.sh','full','--server-cores','64-71','--load-cores','72-79',
            '--load-smt','','--ports','48840-48842','--candidate-binary',
            str(root/f'build/tomokv-iofix3-{arm}')]
    row = dict(name=name, argv=argv,
               extra_env={k:v for k,v in env.items() if k.startswith('GATE_')},
               started=time.time(), expected_exit=expected)
    print('START',name,flush=True)
    with (doc/(name+'.log')).open('w') as log:
        result = subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT)
    row.update(ended=time.time(),exit=result.returncode,expected=result.returncode==expected)
    with (doc/'matrix-status.jsonl').open('a') as out:
        out.write(json.dumps(row)+'\n')
    print('END',name,result.returncode,flush=True)

gate('pad-a-idle-final', 'iofix-deferred', arm='pad-a', expected=1)
gate('post2-correctness-epoll-rerun',
     'wb_policy flip flip_saturated flipctl climonfix debug-0 debug-1 '
     'release_batteries asan_batteries replyoff zc auth',engine='epoll')
for engine in ('uring','epoll'):
    jobs = 'debug-0 debug-1 release_batteries asan_batteries replyoff zc auth'
    if engine == 'uring':
        jobs += ' snapshot-uring snapshot-epoll aof-uring aof-epoll'
    gate(f'post2-fused-{engine}-rerun', jobs,engine=engine,fused=True)
for engine in ('uring','epoll'):
    gate(f'post2-differ-{engine}-rerun','differ-split differ-armed',engine=engine)
print('COMPLETE gate matrix; inspect every exit and ledger',flush=True)
