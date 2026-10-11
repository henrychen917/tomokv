#!/usr/bin/env python3
"""Summarize run_trials.sh outputs: one line per scanned value (classes per trial.py)."""
import json, re, sys
for path in sys.argv[1:]:
    print('==', path)
    for line in open(path):
        if not line.startswith('{'):
            continue
        d = json.loads(line)
        v = re.search(r'large-unit-insns=(\d+)', d['params'])[1]
        print(f"{v:>7} unit {d['unit']} changed {d['A']+d['B']+d['C']+d['D']+d['AOF']+d['R7']+d['CF']:3} hot {d['hot_changed']:3}"
              f" A {d['A']:3} B {d['B']:2} C {d['C']:2} D {d['D']:2} AOF {d['AOF']} R7 {d['R7']} CF {d['CF']:2}"
              f" neB4 {d['neB4']:3} Chot {d['Chot']} Dhot {d['Dhot']}")
