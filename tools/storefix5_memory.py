#!/usr/bin/env python3
"""Finite maxmemory footprint matrix; no throughput measurement."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('arm')
    p.add_argument('--binary', type=Path, required=True)
    p.add_argument('--redis', action='store_true')
    p.add_argument('--port', type=int, default=21630)
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(16, 24))
    dest = ROOT/'docs/storefix5/memory'/a.arm
    dest.mkdir(parents=True, exist_ok=True)
    rows = []
    for mode in (('2s',) if a.redis else ('1s', '2s')):
        for mb in (30, 100):
            for policy in ('allkeys-lru', 'noeviction'):
                for value in (100, 1000):
                    tag = f'{mode}-{mb}mb-{policy}-{value}b'
                    output = dest/(tag+'.json')
                    cmd = [sys.executable, str(ROOT/'tools/storefix5_checks.py'),
                           '--binary', str(a.binary.resolve()), '--mode', mode,
                           '--port', str(a.port), '--cases', 'memory_limit',
                           '--maxmemory', str(mb*1024*1024), '--policy', policy,
                           '--value-size', str(value), '--output', str(output)]
                    if a.redis: cmd += ['--redis']
                    with output.with_suffix('.log').open('w') as log:
                        result = subprocess.run(cmd, env=dict(os.environ, LC_ALL='C'),
                                                stdout=log, stderr=subprocess.STDOUT)
                    rows.append(dict(tag=tag, exit=result.returncode, argv=cmd))
                    print(a.arm, tag, result.returncode, flush=True)
                    (dest/'matrix.json').write_text(json.dumps(rows, indent=2)+'\n')
    sys.exit(any(row['exit'] for row in rows))
