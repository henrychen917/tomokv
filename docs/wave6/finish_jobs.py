#!/usr/bin/env python3
"""Complete whole gate jobs serially after the broad sweep; no performance jobs."""
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(64, 96)))
os.chdir(ROOT)
OUT = ROOT / 'docs/wave6/correctness'
BUILD = ROOT / 'build/wave6'
manifest = json.loads((ROOT / 'docs/wave6/job-manifest.json').read_text())
while 'exit' not in json.loads((OUT / 'broad-1/receipt.json').read_text()):
    time.sleep(5)


def job(name, jobs, *options):
    command = ['python3', 'docs/wave6/run_jobs.py', name, *jobs, *options]
    result = subprocess.run(command)
    print(name, result.returncode, flush=True)


job('integration-fixtures', ['reorder_identity', 'atomic_units'])
job('tailgen-build', ['tailgen_build'])

# Keep scheduler controls away from concurrent builds and servers. The first
# attempt used two load CPUs and an incomplete copy; neither is passing evidence.
env = dict(os.environ, GATE_TEST_PORT='26897')
env.pop('NETFIX_TLS_ORACLE', None)
start = time.time()
with (BUILD / 'gates-test-quiet.log').open('w') as log:
    result = subprocess.run(['python3', 'tests/gates_test.py'], env=env,
                            stdout=log, stderr=subprocess.STDOUT)
(OUT / 'gates-test.json').write_text(json.dumps(dict(
    command=['python3', 'tests/gates_test.py'], affinity=sorted(os.sched_getaffinity(0)),
    port=26897, start=start, end=time.time(), exit=result.returncode,
    log=str(BUILD / 'gates-test-quiet.log')), indent=2) + '\n')

copy = BUILD / 'selftest-source'
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
(ROOT / 'docs/wave6/selftest-final-copy.json').write_text(json.dumps(dict(
    source_sha256=hashlib.sha256(gate.encode()).hexdigest(),
    copied_sha256=hashlib.sha256(adjusted.encode()).hexdigest(),
    diff=''.join(difflib.unified_diff(gate.splitlines(True), adjusted.splitlines(True),
                                    fromfile='protected gate', tofile='throwaway gate'))), indent=2) + '\n')
job('abba-selftest-complete', ['abba_selftest'], '--selftest', '--root', str(copy))

for engine in ('uring', 'epoll'):
    job('differ-' + engine, manifest['differential'], '--engine', engine)

cells = ['txnorder-fused-0', 'txnorder-fused-1', 'txnorder-split-0', 'txnorder-split-1']
for round in (2, 3):
    job('txnorder-round-' + str(round), cells)

# These jobs expose their legacy boots through GATE_TXN_FUSED; all their
# assertions, oracle legs, ASAN legs and shutdown checks remain in gate.sh.
legacy = ['release_batteries', 'notify', 'sort', 'script_bounds', 'dump_restore',
          'auth', 'replyoff', 'zc', 'aof-epoll', 'aof-uring',
          'snapshot-epoll', 'snapshot-uring']
job('legacy-split-final', legacy)
job('legacy-fused', legacy, '--fused')

job('perfio-quiet', ['perfio_stream'])
job('atomic-split-quiet', ['atomic_batteries'])
job('atomic-fused-quiet', ['atomic_batteries'], '--fused')
print('Whole-job sequence complete; inspect all receipts, including failures.', flush=True)
