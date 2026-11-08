#!/usr/bin/env python3
"""Build `make all` plus every job_production_units target, then prove freshness with make -q.

The target lists are read from tests/gate.sh's job_production_units at run time, so this
receipt cannot drift from the gate. CPUs 32-47, -j16. No server, test or workload runs here.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(32, 48)), 'cfgfix2 CPU boundary'
body = re.search(r'^job_production_units\(\)\{\n(.*?)^\}', (ROOT / 'tests/gate.sh').read_text(),
                 re.S | re.M).group(1)
main = re.search(r'make -k -j"\$BUILD_JOBS" \\\n(.*?)>"\$TMPDIR/build.log"', body, re.S).group(1)
units = re.findall(r'build/[A-Za-z0-9_.-]+', main)
assert len(units) >= 50, units
steps = [
    ('all', ['make', '-j16', 'all']),
    ('production-units', ['make', '-k', '-j16'] + units),
    ('mdbqsbr-live-arms', ['make', '-j16', 'mdbqsbr-live-arms']),
    ('blockfix-cost', ['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-j16', 'build/blockfix-cost']),
    ('blockfix2-units', ['make', '-f', 'Makefile', '-f', 'tools/blockfix2.mk', '-j16',
                         'build/blockfix2-unit', 'build/blockfix2-db0-unit']),
]
fresh = [('all', ['make', '-q', 'all'])] + [(t, ['make', '-q', t]) for t in units] + [
    ('blockfix-cost', ['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-q', 'build/blockfix-cost',
                       'build/tomokv.blockfix-cost.sha256']),
    ('blockfix2-units', ['make', '-f', 'Makefile', '-f', 'tools/blockfix2.mk', '-q',
                         'build/blockfix2-unit', 'build/blockfix2-db0-unit'])]
log = ROOT / 'build/cfgfix2/production-units.log'
record = dict(units=units, builds=[], freshness=[])
with log.open('w') as out:
    for label, command in steps:
        began = time.time()
        rc = subprocess.run(['taskset', '-c', '32-47'] + command, cwd=ROOT, stdout=out,
                            stderr=subprocess.STDOUT).returncode
        record['builds'].append(dict(label=label, command=command, returncode=rc,
                                     seconds=round(time.time() - began, 1)))
    for label, command in fresh:
        rc = subprocess.run(command, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
        record['freshness'].append(dict(target=label, returncode=rc))
record['summary'] = dict(builds_failed=sum(b['returncode'] != 0 for b in record['builds']),
                         stale=sum(f['returncode'] != 0 for f in record['freshness']),
                         checked=len(record['freshness']))
out = ROOT / 'docs/cfgfix2/receipts/production-units.json'
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record['summary']))
