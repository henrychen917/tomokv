#!/usr/bin/env python3
"""Verify every production_units build target, plus the release executable."""
import json
import os
from pathlib import Path
import shlex
import subprocess

root = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(16, 32))
body = (root / 'tests/gate.sh').read_text().split('job_production_units(){', 1)[1]
first = body.split('>"$TMPDIR/build.log"', 1)[0]
targets = [s for s in shlex.split(first.replace('\\\n', ' ')) if s.startswith('build/')]
assert len(targets) > 40
queries = [['make', '-q', target] for target in ['all', *targets]]
# The aggregate is phony; verify the two concrete recursive build roots.
queries += [['make', '-q', 'BUILD_ROOT=build/' + arm, 'all'] for arm in
            ('mdbqsbr2-park', 'mdbqsbr2-no-wake')]
queries += [['make', '-f', 'Makefile', '-f', 'tools/blockfix_cost.mk', '-q',
             'build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']]
queries += [['make', '-f', 'Makefile', '-f', 'tools/blockfix2.mk', '-q', target]
            for target in ('build/blockfix2-unit', 'build/blockfix2-db0-unit')]
results = []
for command in queries:
    result = subprocess.run(command, cwd=root, text=True, capture_output=True)
    results.append(dict(command=command, exit_code=result.returncode,
                        stdout=result.stdout, stderr=result.stderr))
(root / 'docs/rootcore/freshness.json').write_text(json.dumps(results, indent=2) + '\n')
bad = [row for row in results if row['exit_code']]
print(json.dumps(dict(queries=len(results), failed=bad), indent=2))
raise SystemExit(bool(bad))
