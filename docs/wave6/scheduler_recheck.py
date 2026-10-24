#!/usr/bin/env python3
"""After whole-job coverage, recheck the repaired scheduler fixture, then build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 96)))
OUT = ROOT / 'docs/wave6/correctness'
BUILD = ROOT / 'build/wave6'
parser = argparse.ArgumentParser()
parser.add_argument('--final-controls', action='store_true')
args = parser.parse_args()
suffix = 'final-controls' if args.final_controls else 'repaired'
wait_for = 'freshness-final.json' if args.final_controls else 'sequence-final.json'
while not (OUT / wait_for).exists():
    time.sleep(5)

release_exits = []
release_jobs = [] if args.final_controls else [('release-split-repaired', []), ('release-fused-repaired', ['--fused'])]
for name, options in release_jobs:
    result = subprocess.run(['python3', 'docs/wave6/run_jobs.py', name,
                             'release_batteries', *options])
    release_exits.append(result.returncode)

env = dict(os.environ, GATE_TEST_PORT='26897')
env.pop('NETFIX_TLS_ORACLE', None)
start = time.time()
logfile = OUT / ('gates-test-' + suffix + '.log')
with logfile.open('w') as log:
    result = subprocess.run(['python3', 'tests/gates_test.py'], env=env,
                            stdout=log, stderr=subprocess.STDOUT)
(OUT / ('gates-test-' + suffix + '.json')).write_text(json.dumps(dict(
    command=['python3', 'tests/gates_test.py'], affinity=sorted(os.sched_getaffinity(0)),
    port=26897, start=start, end=time.time(), exit=result.returncode,
    log=str(logfile.relative_to(ROOT))), indent=2) + '\n')
print('Repaired standalone scheduler:', result.returncode, flush=True)
scheduler_exit = result.returncode

copy = BUILD / ('selftest-' + suffix + '-source')
for name in ('tests', 'tools', '.githooks', 'src'):
    shutil.copytree(ROOT / name, copy / name, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in [ROOT / 'Makefile', ROOT / '.gitignore', *ROOT.glob('*.md')]:
    shutil.copy2(path, copy / path.name)
for rel in ('docs/CONFIGURATION.md', 'docs/cd13b/audit.json',
            'docs/dispatchfix/pre-sha256.txt', 'docs/flakeaudit2/triage.json',
            'docs/lbplanner/generic-cells.txt', 'docs/lbplanner/multidb-cells.txt'):
    (copy / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / rel, copy / rel)
gate = (ROOT / 'tests/gate.sh').read_text()
adjusted = re.sub(r'^EXPECT_QUICK=739$', 'EXPECT_QUICK=768', gate, flags=re.M)
adjusted = re.sub(r'^EXPECT_FULL=756\b', 'EXPECT_FULL=785', adjusted, flags=re.M)
assert adjusted != gate
(copy / 'tests/gate.sh').write_text(adjusted)
(ROOT / ('docs/wave6/selftest-' + suffix + '-copy.json')).write_text(json.dumps(dict(
    source_sha256=hashlib.sha256(gate.encode()).hexdigest(),
    copied_sha256=hashlib.sha256(adjusted.encode()).hexdigest(),
    gates_test_sha256=hashlib.sha256((copy / 'tests/gates_test.py').read_bytes()).hexdigest(),
    edits=['EXPECT_QUICK 739->768', 'EXPECT_FULL 756->785'],
    fixture='Unmodified merged 785-row label fixture'), indent=2) + '\n')
result = subprocess.run(['python3', 'docs/wave6/run_jobs.py', 'abba-selftest-' + suffix,
                         'abba_selftest', '--selftest', '--root', str(copy)], env=env)
print('Repaired ABBA whole job:', result.returncode, flush=True)
abba_exit = result.returncode

# All correctness children have reaped before any compile/freshness work starts.
previous = json.loads((OUT / 'build-final.json').read_text())
targets = previous['targets'] + ['build/tailgen']
start = time.time()
digest = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
command = ['make', '-j32', *targets]
with (BUILD / 'build-freshness-final.log').open('w') as log:
    result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
freshness = []
for target in targets:
    check = subprocess.run(['make', '-q', target], capture_output=True, text=True)
    freshness.append(dict(target=target, exit=check.returncode, output=check.stdout + check.stderr))
after = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
receipt = dict(command=command, affinity=sorted(os.sched_getaffinity(0)), start=start,
    end=time.time(), exit=result.returncode, freshness=freshness,
    binary_sha256=digest, binary_sha256_after=after,
    tailgen_note='Compile only; build-only gate job selection was refused; generator never launched.')
(OUT / 'freshness-final.json').write_text(json.dumps(receipt, indent=2) + '\n')
assert digest == after == previous['binary_sha256']
assert result.returncode == 0 and all(row['exit'] == 0 for row in freshness)
print('Final build/freshness passed; POST unchanged.', flush=True)
assert scheduler_exit == abba_exit == 0 and not any(release_exits)
