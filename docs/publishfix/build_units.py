#!/usr/bin/env python3
"""Build exactly job_production_units' targets, without running the gate."""
import json
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[2]
assert set(os.sched_getaffinity(0)) <= set(range(96, 112))
out = root / 'build/publishfix/production-units'
out.mkdir(parents=True, exist_ok=True)
body = (root / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\n}', 1)[0]
targets = sorted(set(re.findall(r'build/[A-Za-z0-9_.-]+', body)))
assert targets and 'build/publishfix-unit' in targets
(out / 'targets.json').write_text(json.dumps(targets, indent=2) + '\n')
prefix = ['taskset', '-c', '96-111', 'make']
rows = []
for label, args in [('all', ['-j16', 'all']), ('units', ['-k', '-j16', *targets]),
                    ('mdbqsbr-live-arms', ['-j16', 'mdbqsbr-live-arms'])]:
    with (out / (label + '.log')).open('w') as f:
        rc = subprocess.run(prefix + args, cwd=root, stdout=f, stderr=subprocess.STDOUT).returncode
    rows.append(dict(label=label, argv=prefix + args, rc=rc))
    print(json.dumps(rows[-1]), flush=True)
for target in ['all', *targets]:
    args = prefix + ['-q', target]
    rc = subprocess.run(args, cwd=root).returncode
    rows.append(dict(label=target, argv=args, rc=rc))
    print(json.dumps(rows[-1]), flush=True)
for name, flags in [('park', '-DTOMO_MDBQSBR_LIVE_PARK'),
                    ('no-wake', '-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')]:
    args = prefix + [f'BUILD_ROOT=build/mdbqsbr2-{name}',
                     'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread ' + flags,
                     '-q', 'all']
    rc = subprocess.run(args, cwd=root).returncode
    rows.append(dict(label='mdbqsbr-' + name + '-fresh', argv=args, rc=rc))
    print(json.dumps(rows[-1]), flush=True)
(out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
raise SystemExit(any(r['rc'] != 0 for r in rows))
