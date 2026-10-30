#!/usr/bin/env python3
"""Temporary sequential launcher; all actual tests use the gate job interface."""
import json, os, subprocess, time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/wave11'
os.sched_setaffinity(0,set(range(64,96)))
os.chdir(ROOT)
while not (DOC/'jobs/landing-main-2s-uring.json').exists():
    time.sleep(20)
rows=[]
def run(name, command, env=None):
    print('START', name, flush=True)
    t=time.monotonic()
    with (ROOT/'build/wave11'/('finish-'+name+'.log')).open('w') as f:
        result=subprocess.run(command, stdout=f, stderr=subprocess.STDOUT, env=env)
    rows.append(dict(name=name,command=command,exit=result.returncode,seconds=time.monotonic()-t))
    (DOC/'finish-campaign.json').write_text(json.dumps(rows,indent=2)+'\n')
    print('DONE',name,result.returncode,flush=True)

run('aof-isolated', ['python3','docs/wave11/run_jobs.py','landing-aof-isolated','aof-epoll',
    '--binary','build/wave11/tomokv-POST','--single-slot'])
run('tcl', ['python3','docs/wave11/run_jobs.py','landing-tcl','redis_tcl','compat2',
    '--binary','build/wave11/tomokv-POST','--asan-binary','build/wave11/tomokv-ASAN'])
run('sidecars', ['python3','docs/wave11/run_jobs.py','landing-adjacent-units','blockfix_registry','blockfix2',
    '--binary','build/wave11/tomokv-POST','--single-slot'])
for phase in ('secondary','differ','bounds0','quiet'):
    run(phase,['python3','docs/wave11/campaign.py',phase,'--asan-binary','build/wave11/tomokv-ASAN'])
run('negative-tcl',['python3','docs/wave11/regressions.py'])
copy=ROOT/'build/wave11/selftest-source-full'
# The initial attempt's partial directory copy omitted root hook/report inputs.
# Retain that failed receipt; every new preparation exports the complete tree.
subprocess.run(['python3',str(DOC/'prepare_selftest.py'),str(copy)],check=True)
run('abba-selftest',['python3','docs/wave11/run_jobs.py','landing-abba-selftest','abba_selftest',
    '--root',str(copy),'--binary','build/wave11/tomokv-POST','--single-slot','--port','20080'])
run('gates-test',['taskset','-c','88-95','python3','tests/gates_test.py'],
    dict(os.environ,GATE_TEST_PORT='20098',LC_ALL='C'))
print('FINISHED',flush=True)
