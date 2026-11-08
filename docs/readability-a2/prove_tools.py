#!/usr/bin/env python3
"""Run A1's unchanged 52-case matrix within this process's authorized CPU mask."""
import importlib.util
import os
from pathlib import Path

path = Path(__file__).resolve().parents[1] / 'readability-a1/prove_tools.py'
spec = importlib.util.spec_from_file_location('a1_proof', path)
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)
cases = proof.cases()
changed = 0
for name, command, _, _ in cases:
    if '--cores' in command:
        command[command.index('--cores') + 1] = ','.join(map(str, sorted(os.sched_getaffinity(0))))
        changed += 1
assert changed == 1, 'review the A1 proof runner resource inventory'
proof.cases = lambda: cases

if __name__ == '__main__':
    raise SystemExit(proof.main())
