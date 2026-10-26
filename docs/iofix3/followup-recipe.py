import json
import os
from pathlib import Path
import subprocess
import time

root = Path('/home/user/Projects/cx-iofix3')
os.chdir(root)
doc = root/'docs/iofix3'
while 'COMPLETE remaining sequence' not in (doc/'remaining-sequence.log').read_text():
    time.sleep(2)

def gate(name, jobs, arm='post2', fused=False, expected=0):
    env = dict(os.environ, GATE_ONLY_JOBS=jobs, GATE_NET_IO='epoll',
               GATE_ZC_NET_IO='epoll', GATE_SHUTDOWN_NET_IO='epoll',
               GATE_TXN_FUSED=str(int(fused)), GATE_TEST_PORT='48898')
    argv = ['python3','tools/iofix3_ports.py','--ports','48830-48832','--',
            'tests/gate.sh','full','--server-cores','64-71','--load-cores','72-79',
            '--load-smt','','--ports','48830-48832','--candidate-binary',
            str(root/f'build/tomokv-iofix3-{arm}')]
    row = dict(name=name, argv=argv, extra_env={k:v for k,v in env.items() if k.startswith('GATE_')},
               started=time.time(), expected_exit=expected)
    print('START', name, flush=True)
    with (doc/(name+'.log')).open('w') as log:
        result = subprocess.run(argv,env=env,stdout=log,stderr=subprocess.STDOUT)
    row.update(ended=time.time(), exit=result.returncode, expected=result.returncode==expected)
    with (doc/'final-status.jsonl').open('a') as out:
        out.write(json.dumps(row)+'\n')
    print('END', name, result.returncode, flush=True)

gate('pad-a-idle-rerun', 'iofix-deferred', arm='pad-a', expected=1)
gate('post4-wb-epoll', 'wb_policy', arm='post4')
gate('post8-wb-epoll', 'wb_policy', arm='post8')
gate('post2-fused-aof', 'aof-uring aof-epoll', fused=True)

checks = json.loads((doc/'production-freshness.json').read_text())
for row in checks:
    result = subprocess.run(row['argv'],capture_output=True,text=True)
    row.update(exit=result.returncode,stdout=result.stdout,stderr=result.stderr)
(doc/'production-freshness-final.json').write_text(json.dumps(checks,indent=2)+'\n')
print('FRESHNESS',len(checks),sum(row['exit'] == 0 for row in checks),flush=True)
assert all(row['exit']==0 for row in checks), 'freshness failure'
print('COMPLETE followup validation; inspect every exit and ledger',flush=True)
