import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path('/home/user/Projects/cx-iofix3')
os.chdir(ROOT)
DOC = ROOT / 'docs/iofix3'
FLAGS = '-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread'
BASE_ENV = dict(os.environ, GATE_TEST_PORT='48898')
STATUS = DOC / 'run-status.jsonl'

def step(name, argv, extra=None, expected=0):
    env = dict(BASE_ENV, **(extra or {}))
    start = time.time()
    row = dict(name=name, argv=argv, extra_env=extra or {}, started=start, expected_exit=expected)
    with STATUS.open('a') as out:
        out.write(json.dumps(dict(row, event='start'))+'\n')
    print('START', name, flush=True)
    with (DOC/(name+'.log')).open('w') as log:
        result = subprocess.run(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
    row.update(event='end', ended=time.time(), exit=result.returncode, expected=result.returncode==expected)
    with STATUS.open('a') as out:
        out.write(json.dumps(row)+'\n')
    print('END', name, result.returncode, flush=True)
    return result.returncode

def gate(name, jobs, arm='post2', engine='uring', fused=False, expected=0):
    extra = dict(GATE_ONLY_JOBS=jobs, GATE_NET_IO=engine, GATE_ZC_NET_IO=engine,
                 GATE_SHUTDOWN_NET_IO=engine, GATE_DIFFER_NET_IO=engine,
                 GATE_TXN_FUSED=str(int(fused)))
    return step(name, ['python3','tools/iofix3_ports.py','--ports','48830-48832','--',
                      'tests/gate.sh','full','--server-cores','64-71','--load-cores','72-79',
                      '--load-smt','','--ports','48830-48832','--candidate-binary',
                      str(ROOT/f'build/tomokv-iofix3-{arm}')], extra, expected)

# Serialize after the already running gate, including its final owned-child cleanup.
while 'GATE(PARTIAL):' not in (DOC/'post2-correctness-uring.log').read_text():
    time.sleep(2)

if step('post2-rebuild', ['make','-j16','all']):
    raise SystemExit('POST2 rebuild failed')
shutil.copy2(ROOT/'build/tomokv-iofix3-post2', ROOT/'build/tomokv-iofix3-post2-initial')
shutil.copy2(ROOT/'build/tomokv', ROOT/'build/tomokv-iofix3-post2')
step('identity-post2-final', ['python3','tools/iofix3_artifacts.py','identity',
     '--pre','build/tomokv-iofix3-pre','--post','build/tomokv-iofix3-post2',
     '--output','docs/iofix3/identity-post2-final'])
step('pad-a-final', ['python3','tools/iofix3_artifacts.py','pad',
     '--pre','build/tomokv-iofix3-pre','--post','build/tomokv-iofix3-post2',
     '--output','build/tomokv-iofix3-pad-a','--receipt','docs/iofix3/pad-a-final.json'])
gate('post2-recheck-uring', 'iofix-deferred iofix-sleep iofix-signal wb_policy wbland_units '
     'wb_rule_units climonfix release_batteries flip auth atomic_units splitlocal_units '
     'reorder_engagement reorder_identity')
gate('pad-a-idle-gate', 'iofix-deferred', arm='pad-a', expected=1)
for arm, multiplier in [('pre',None),('post2',2)]:
    argv = ['python3','tools/wave5b_trace.py','prepare',f'iofix3-{arm}',
            '--ref','3700b51d7' if multiplier is None else 'working',
            '--build-cores','64-79','--jobs','16','--output-dir','docs/iofix3/probe']
    if step(f'trace-{arm}-build', argv):
        raise SystemExit(f'trace {arm} build failed; fixed-count dependent step not run')
step('fixed-count', ['python3','tools/iofix3_ports.py','--ports','48820-48820','--',
                    'python3','tools/wave5b_trace.py','run','--arms',
                    'iofix3-pre','iofix3-post2',
                    '--name','fixed-count','--repeats','3','--requests','2048',
                    '--server-cores','64-71','--load-cores','72-79','--port','48820',
                    '--output-dir','docs/iofix3/probe'])

gate('post2-correctness-epoll', 'wb_policy flip flip_saturated flipctl climonfix debug-0 debug-1 '
     'release_batteries asan_batteries replyoff zc auth', engine='epoll')
for engine in ('uring','epoll'):
    jobs = 'debug-0 debug-1 release_batteries asan_batteries replyoff zc auth'
    if engine == 'uring':
        jobs += ' snapshot-uring snapshot-epoll'
    gate(f'post2-fused-{engine}', jobs, engine=engine, fused=True)
for engine in ('uring','epoll'):
    gate(f'post2-differ-{engine}', 'differ-split differ-armed', engine=engine)
print('COMPLETE remaining sequence; inspect every exit and ledger', flush=True)
