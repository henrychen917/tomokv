#!/usr/bin/env python3
"""Compare the unchanged single-slot scheduler deadline on PRE and POST plans."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tests'))
from gates_test import SchedulerWiring

assert os.sched_getaffinity(0) <= set(range(16, 32))
cpus = sorted(os.sched_getaffinity(0))[-4:]
out = root / 'build/rootcore/scheduler'
out.mkdir(parents=True, exist_ok=True)
pre = out / 'PRE-gate.sh'
pre.write_bytes(subprocess.check_output(['git', 'show', '7d2f8a205:tests/gate.sh']))

stub = '''GATE_PARTIAL=0
start_workers(){ :; }
collect_job(){
  case "$1" in
    differ-split) printf '%s\\n' differ-split-0 differ-split-1 differ-equivalence;;
    differ-armed) printf '%s\\n' differ-armed-0 differ-armed-1;;
    *) printf '%s\\n' "$1";;
  esac
}
'''
for name, path in [('PRE', pre), ('POST', root / 'tests/gate.sh')]:
    gate = path.read_text()
    quick = gate[gate.index('\nstart_workers\n'):gate.index('\n# One correctness row, before the quick exit.')]
    full = gate[gate.index('\ncollect_job asan_batteries\n'):gate.index('\n# Every worker has reaped')]
    result = subprocess.run(['bash', '-uc', stub + quick + full], cwd=root,
                            text=True, capture_output=True, check=True)
    SchedulerWiring.canonical = result.stdout.splitlines()
    SchedulerWiring.fixture_cpus = cpus
    probe = SchedulerWiring('test_one_slot_uses_the_same_queue_without_losing_coverage')
    started = time.monotonic()
    receipt = dict(arm=name, cpus=cpus, jobs=len(SchedulerWiring.canonical),
                   started=datetime.datetime.now(datetime.timezone.utc).isoformat())
    try:
        result = probe._run_scheduler(slots=1, _cpus=cpus, _gate_path=path)
        receipt.update(passed=True, counts=result['counts'])
        (out / (name + '.log')).write_text(result['output'])
    except AssertionError as error:
        receipt.update(passed=False)
        (out / (name + '.log')).write_text(str(error) + '\n')
    receipt['seconds'] = time.monotonic() - started
    (out / (name + '.json')).write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt), flush=True)
