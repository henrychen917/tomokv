#!/usr/bin/env python3
"""Build all current gate-owned production targets and check each with make -q."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/wave4c'
text = (ROOT / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1].split('\n}', 1)[0]
targets = re.findall(r'\bbuild/[a-zA-Z0-9_-]+', text.split('  # -q', 1)[0])
assert len(targets) == len(set(targets)) == 37, targets
targets = ['all', *targets, 'mdbqsbr-live-arms']
command = ['make', '-k', '-j32', *targets]
start = time.monotonic()
with (OUT / 'production-build.log').open('w') as log:
    status = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
rows = []
for target in targets:
    check = ['make', '-q', target]
    result = subprocess.run(check, cwd=ROOT, capture_output=True, text=True)
    rows.append(dict(target=target, argv=check, returncode=result.returncode,
                     output=result.stdout + result.stderr))
result = dict(argv=command, returncode=status, seconds=time.monotonic() - start,
              binary_sha256=hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest(),
              freshness=rows)
(ROOT / 'docs/wave4c/production-build.json').write_text(json.dumps(result, indent=2) + '\n')
print('build', status, 'fresh', sum(r['returncode'] == 0 for r in rows), '/', len(rows), flush=True)
raise SystemExit(status != 0 or any(r['returncode'] for r in rows))
