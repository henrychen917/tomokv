#!/usr/bin/env python3
"""Finish the standalone harness and remaining perfio owner on disjoint CPUs."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
ROOT = Path(__file__).resolve().parents[2]; os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64,96)))
OUT=ROOT/'docs/wave7b/final-checks'; OUT.mkdir(exist_ok=True)
repeats=json.loads((ROOT/'docs/wave7b/repetitions.json').read_text())
assert sum('abba' in r['name'] for r in repeats)==10
assert sum(r['name'].startswith('repeat-flip-') for r in repeats)==10
assert all(r['exit']==0 for r in repeats)
source_files=('tests/gates_test.py','tests/gate_history.py','tests/gate_receipt.py','tests/perfio.py')
receipt=dict(start=time.time(), affinity=sorted(os.sched_getaffinity(0)),
             source_files={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in source_files},
             binary_sha256=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest())

def run(tag, command, env):
    start=time.monotonic()
    with (OUT/(tag+'.log')).open('w') as log:
        result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
    return dict(command=command,exit=result.returncode,seconds=time.monotonic()-start)
def perfio_after_peers(command, env):
    # ABBA is complete; let any already-started background feature job finish
    # before running perfio's fixed latency guard on that slot. Standalone
    # scheduler tests can use their own disjoint CPUs in the meantime.
    while True:
        pending=False
        for path in (ROOT/'docs/wave7b/correctness').glob('peer-feature-*/receipt.json'):
            try: data=json.loads(path.read_text())
            except json.JSONDecodeError: pending=True; continue
            if 'exit' not in data: pending=True
            else: assert data['exit']==0, path
        if not pending: break
        time.sleep(.2)
    return run('perfio-owner', command, env)

env=dict(os.environ,LANG='en_US.UTF-8');env.pop('LC_ALL',None)
standalone=dict(env,GATE_TEST_PORT='26896',PYTHONPATH=str(ROOT/'docs/wave7b/observe'),
                WAVE7B_TIMINGS=str(OUT/'timings'))
with ThreadPoolExecutor(2) as pool:
    a=pool.submit(run,'gates_test',['taskset','-c','64-79','python3','tests/gates_test.py'],standalone)
    b=pool.submit(perfio_after_peers,['taskset','-c','80-95','python3','docs/wave7b/run_job.py',
        'perfio-owner','perfio_stream','--server-cores','80-87','--load-cores','88-95',
        '--ports','26830-26839','--test-port','26897'],env)
    receipt['standalone']=a.result();receipt['perfio_owner']=b.result()
receipt['freshness']=[]
for row in json.loads((ROOT/'docs/wave7b/build-proof/receipt.json').read_text())['freshness']:
    result=subprocess.run(['taskset','-c','64-95',*row['command']],env=env,text=True,capture_output=True)
    receipt['freshness'].append(dict(command=row['command'],exit=result.returncode,output=result.stdout+result.stderr))
receipt['end']=time.time()
receipt['binary_sha256_after']=hashlib.sha256((ROOT/'build/tomokv').read_bytes()).hexdigest()
receipt['standalone_summary']=re.findall(r'Ran \d+ tests in [^\n]+|^OK$|^FAILED[^\n]*',
                                       (OUT/'gates_test.log').read_text(),re.MULTILINE)
(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
print(json.dumps({k:v for k,v in receipt.items() if k not in ('freshness','source_files')}))
assert receipt['standalone']['exit']==receipt['perfio_owner']['exit']==0
assert all(r['exit']==0 for r in receipt['freshness'])
assert receipt['binary_sha256']==receipt['binary_sha256_after']
