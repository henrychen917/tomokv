#!/usr/bin/env python3
"""Temporary sequential launcher; all actual tests use the gate job interface."""
import json, os, shutil, subprocess, time
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
copy=ROOT/'build/wave11/selftest-source'
for directory in ('src','tests','tools','third_party','calib'):
    shutil.copytree(ROOT/directory,copy/directory,dirs_exist_ok=True)
shutil.copy2(ROOT/'Makefile',copy/'Makefile')
gate=copy/'tests/gate.sh';s=gate.read_text()
assert s.count('EXPECT_QUICK=946\n')==1 and s.count('EXPECT_FULL=963 ')==1
gate.write_text(s.replace('EXPECT_QUICK=946\n','EXPECT_QUICK=977\n').replace('EXPECT_FULL=963 ','EXPECT_FULL=994 '))
shutil.copy2(DOC/'landing-label-fixture.json',copy/'tests/fixtures/nullrefresh-ledger-labels.json')
run('abba-selftest',['python3','docs/wave11/run_jobs.py','landing-abba-selftest','abba_selftest',
    '--root',str(copy),'--binary','build/wave11/tomokv-POST','--single-slot','--port','20080'])
run('gates-test',['taskset','-c','88-95','python3','tests/gates_test.py'],
    dict(os.environ,GATE_TEST_PORT='20098',LC_ALL='C'))
print('FINISHED',flush=True)
