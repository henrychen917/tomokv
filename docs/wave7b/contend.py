#!/usr/bin/env python3
"""Owned CPU contention, stopped/reaped by this parent; no server or benchmark."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
p=argparse.ArgumentParser(); p.add_argument('stop', type=Path); p.add_argument('--cpus', default='64-95'); a=p.parse_args()
cpus=[]
for field in a.cpus.split(','):
    ends=[int(v) for v in field.split('-')]; cpus.extend(range(ends[0], ends[-1]+1))
assert set(cpus) <= set(range(64,96))
children=[]
try:
    for cpu in cpus:
        children.append(subprocess.Popen(['taskset','-c',str(cpu),sys.executable,'-c',
            'import hashlib; value=b"wave7b correctness contention"*1024\nwhile True: hashlib.sha256(value).digest()']))
    print('owned contention PIDs', [p.pid for p in children], flush=True)
    while not a.stop.exists(): time.sleep(.2)
finally:
    for child in children:
        if child.poll() is None: child.terminate()
    for child in children: child.wait(timeout=5)
