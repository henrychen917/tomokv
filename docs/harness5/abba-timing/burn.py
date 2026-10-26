#!/usr/bin/env python3
"""Owned CPU contention for landing-like ABBA self-test timing (wave7b method).

One busy hashing process per CPU in --cpus (must stay inside 32-47), stopped and
reaped when STOP exists. No server, no network, no load generator.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import time

p = argparse.ArgumentParser()
p.add_argument('stop', type=Path)
p.add_argument('--cpus', required=True)
a = p.parse_args()
cpus = []
for field in a.cpus.split(','):
    ends = [int(v) for v in field.split('-')]
    cpus.extend(range(ends[0], ends[-1] + 1))
assert cpus and set(cpus) <= set(range(32, 48)), cpus
children = []
try:
    for cpu in cpus:
        children.append(subprocess.Popen(['taskset', '-c', str(cpu), sys.executable, '-c',
            'import hashlib\nvalue = b"harness5 landing contention" * 1024\nwhile True: hashlib.sha256(value).digest()']))
    print('owned contention PIDs', [c.pid for c in children], flush=True)
    while not a.stop.exists():
        time.sleep(0.2)
finally:
    for child in children:
        if child.poll() is None:
            child.terminate()
    for child in children:
        child.wait(timeout=10)
