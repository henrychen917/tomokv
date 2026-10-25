#!/usr/bin/env python3
"""Ten whole ABBA/FLIP jobs on three disjoint active slots; never a full gate."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import threading
import time

ROOT=Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64,96)))
rows=[]; lock=threading.Lock(); failed=threading.Event(); done=threading.Event()

def record(name, rc, seconds):
    with lock:
        rows.append(dict(name=name, exit=rc, seconds=seconds))
        (ROOT/'docs/wave7b/repetitions.json').write_text(json.dumps(rows,indent=2)+'\n')
    print(name,rc,round(seconds,2),flush=True)
    if rc: failed.set()

def run(name,jobs,server,load,ports,test_port):
    command=['python3','docs/wave7b/run_job.py',name,*jobs,'--server-cores',server,
             '--load-cores',load,'--ports',ports,'--test-port',str(test_port)]
    timings=ROOT/'build/wave7b/repetition-timings'/name
    env=dict(os.environ, PYTHONPATH=str(ROOT/'docs/wave7b/observe'), WAVE7B_TIMINGS=str(timings))
    begin=time.monotonic()
    rc=subprocess.run(command,env=env).returncode
    record(name,rc,time.monotonic()-begin)
    return rc

def first_slot():
    # The first job was started interactively before this controller. Count it
    # only after the real job receipt has its final exit and unchanged hash.
    path=ROOT/'docs/wave7b/correctness/abba-smoke/receipt.json'
    while True:
        try: receipt=json.loads(path.read_text())
        except (FileNotFoundError,json.JSONDecodeError): receipt={}
        if 'exit' in receipt: break
        time.sleep(.5)
    record('abba-smoke',receipt['exit'],receipt['end']-receipt['start'])
    for i in range(2,6):
        if failed.is_set(): break
        run(f'repeat-abba-{i:02}', ['abba_selftest'], '64-77','88-89','26800-26809',26890)

def second_slot():
    for i in range(6,11):
        if failed.is_set(): break
        run(f'repeat-abba-{i:02}', ['abba_selftest'], '72-85','90-91','26810-26819',26891)

def third_slot():
    # Surplus selected server CPUs satisfy the planner's 16-CPU minimum. Only
    # the first eight (80-87) host this slot; all prerequisites are already fresh.
    for i in range(1,11):
        run(f'repeat-flip-{i:02}', ['flip'], '80-91,94-95','92-93','26820-26829',26892)
    i=0
    while not done.is_set() and not failed.is_set():
        i+=1
        run(f'peer-feature-{i:02}', ['feature-split-0','feature-armed-0'],
            '80-91,94-95','92-93','26820-26829',26892)

with ThreadPoolExecutor(max_workers=3) as pool:
    a=pool.submit(first_slot); b=pool.submit(second_slot); c=pool.submit(third_slot)
    try: a.result(); b.result()
    finally: done.set()
    c.result()
raise SystemExit(int(failed.is_set()))
