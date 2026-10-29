#!/usr/bin/env python3
"""Continue the selected correctness legs after their port range is released."""
import argparse, json, os, subprocess, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser()
p.add_argument('index', type=int)
a = p.parse_args()
os.sched_setaffinity(0, set(range(32, 48)))
row = json.loads((ROOT / 'docs/rlfix4/remaining-jobs.json').read_text())[a.index]
receipt = ROOT / 'docs/rlfix4/jobs' / (row['wait'] + '.json')
deadline = time.monotonic() + 3 * 3600
while not receipt.exists():
    if time.monotonic() >= deadline:
        raise SystemExit('preceding job did not finish; no port reuse')
    time.sleep(10)
# A failed earlier suite still releases its listeners and must not suppress the
# independent remaining legs. The failed receipt remains part of the report.
command = ['python3', 'tools/rlfix4_jobs.py', row['name'], *row['jobs'],
           '--engine', row['engine'], '--server-cores', row['server'],
           '--load-cores', row['load'], '--port', str(row['port'])]
if row.get('fused'):
    command.append('--fused')
raise SystemExit(subprocess.call(command, cwd=ROOT))
