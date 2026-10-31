#!/usr/bin/env python3
"""Build exactly the gate's production prerequisites at lane -j16, then check freshness."""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

root = Path(__file__).resolve().parents[1]
out = root / 'docs/trackorder/units'
out.mkdir(parents=True, exist_ok=True)
assert os.sched_getaffinity(0) <= set(range(16))
body = (root / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\n}', 1)[0]
first = body.split('make -k -j"$BUILD_JOBS"', 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
targets = shlex.split(first.replace('\\\n', ' '))
assert all(t.startswith('build/') for t in targets)
groups = [([], ['all', *targets]), ([], ['mdbqsbr-live-arms']),
          (['-f', 'Makefile', '-f', 'tools/blockfix_cost.mk'], ['build/blockfix-cost']),
          (['-f', 'Makefile', '-f', 'tools/blockfix2.mk'], ['build/blockfix2-unit', 'build/blockfix2-db0-unit'])]
marker = root / 'build/trackorder/units-running'
marker.write_text(str(os.getpid()))
rows = []
try:
    for i, (flags, names) in enumerate(groups):
        command = ['taskset', '-c', '0-15', 'make', *flags, '-k', '-j16', *names]
        with (out / f'build-{i}.log').open('w') as log:
            rc = subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT).returncode
        rows.append(dict(argv=command, rc=rc))
    checks = []
    for flags, names in groups:
        for target in names:
            command = ['make', *flags, '-q', target]
            checks.append(dict(argv=command, rc=subprocess.run(command, cwd=root).returncode))
    command = ['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-q',
               'build/tomokv.blockfix-cost.sha256']
    checks.append(dict(argv=command, rc=subprocess.run(command, cwd=root).returncode))
    (out / 'result.json').write_text(json.dumps(dict(builds=rows, freshness=checks), indent=2) + '\n')
finally:
    marker.unlink()
raise SystemExit(any(r['rc'] for r in rows + checks))
