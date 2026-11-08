#!/usr/bin/env python3
"""Check all production-unit job targets after the gate has built them."""
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
gate = (ROOT / 'tests/gate.sh').read_text()
job = gate.split('job_production_units(){\n', 1)[1].split('\n}\n', 1)[0]
primary = job.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
targets = re.findall(r'build/[a-zA-Z0-9_-]+', primary)
assert len(targets) == len(set(targets)) == 61, 'production-unit inventory changed'
commands = [['make', '-q', name] for name in ['all', *targets]]

# The phony mdbqsbr-live-arms recipe always needs execution under make -q;
# check the two concrete recursive all targets it builds instead.
for suffix, defines in (
        ('park', '-DTOMO_MDBQSBR_LIVE_PARK'),
        ('no-wake', '-DTOMO_MDBQSBR_LIVE_PARK -DTOMO_MDBQSBR_NO_WAKE')):
    commands.append(['make', '-q', f'BUILD_ROOT=build/mdbqsbr2-{suffix}',
                     'CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread ' + defines,
                     'all'])
for target in ('build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256'):
    commands.append(['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-q', target])
for target in ('build/blockfix2-unit', 'build/blockfix2-db0-unit'):
    commands.append(['make', '-f', 'Makefile', '-f', 'tools/blockfix2.mk', '-q', target])

env = dict(os.environ, LC_ALL='C', TOMO_INFO_GIT_SHA1='5c363128', TOMO_INFO_GIT_DIRTY='0')
rows = []
for command in commands:
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
    rows.append(dict(command=command, exit=result.returncode,
                     stdout=result.stdout, stderr=result.stderr))
result = dict(primary_unit_targets=len(targets), checks=len(rows),
              passed=sum(row['exit'] == 0 for row in rows), rows=rows)
print(json.dumps(result, indent=2))
raise SystemExit(any(row['exit'] for row in rows))
