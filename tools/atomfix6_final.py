#!/usr/bin/env python3
"""Final harness, production-target freshness, and delivered-arm identity checks."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
os.environ['LC_ALL'] = 'C'
os.environ['GATE_TEST_PORT'] = '21798'
out = Path('docs/atomfix6/final-checks')
out.mkdir(parents=True, exist_ok=True)
rows = []

def run(label, argv):
    with (out / (label + '.log')).open('w') as log:
        result = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT)
    row = dict(label=label, argv=argv, rc=result.returncode)
    rows.append(row)
    print(label, result.returncode, flush=True)

run('gates-test', ['python3', 'tests/gates_test.py'])
targets = Path('docs/atomfix6/production-targets.txt').read_text().split()
assert len(targets) == 55
run('production-build', ['make', '-j13', 'all', *targets])
for target in ['all', *targets,
    'build/atomfix6-unit', 'build/atomfix6-db0-unit',
    'build/atomfix6-asan', 'build/atomfix6-db0-asan',
    'build/atomfix6-tsan', 'build/atomfix6-db0-tsan',
    'build/atomfix6-park-unit', 'build/atomfix6-park-db0-unit',
    'build/atomfix6-queue-asan', 'build/atomfix6-queue-tsan']:
    run('fresh-' + target.replace('/', '-'), ['make', '-q', target])
for label, makefile, extra in [
    ('blockfix', 'tools/blockfix_cost.mk', ['build/blockfix-cost', 'build/tomokv.blockfix-cost.sha256']),
    ('blockfix2', 'tools/blockfix2.mk', ['build/blockfix2-unit', 'build/blockfix2-db0-unit']),
    ('park-asan', 'tools/atomfix6.mk', ['build/atomfix6-park-asan'])]:
    run('fresh-' + label, ['make', '-f', 'Makefile', '-f', makefile, '-q', *extra])
run('diff-check', ['git', 'diff', '--check'])
arms = json.loads(Path('docs/atomfix6/arms.json').read_text())
for arm in arms:
    path = Path(arm['path'])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    rows.append(dict(label='identity-' + arm['arm'], sha256=digest,
        bytes=path.stat().st_size, rc=int(digest != arm['sha256'])))
(out / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
failures = [r for r in rows if r['rc']]
print('Final checks:', len(rows), 'failures:', failures, flush=True)
raise SystemExit(bool(failures))
