#!/usr/bin/env python3
"""Rerun the whole harness after the one-slot fixture repair, on a quiet allocation."""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
out = ROOT / 'docs/wave7/correctness'
env = dict(os.environ, LANG='en_US.UTF-8', GATE_TEST_PORT='26897')
env.pop('LC_ALL', None)
env.pop('NETFIX_TLS_ORACLE', None)
# Diagnose the observed limited-file abort first, while this allocation is
# quiet. Each call retains the complete target/oracle matrix of the owning job.
for name, jobs in [('watch-diagnostic', ['datafix2_watch', 'serverfix_config']),
        ('persistence-final', ['config_unit', 'persistfix2_lastsave',
        'persistfix2_shutdown', 'persistfix2_commands', 'persistfix2_errors']),
        *[(f'persistence-errors-repeat-{index}', ['persistfix2_errors']) for index in range(1, 4)]]:
    check = subprocess.run(['python3', 'docs/wave7/run_jobs.py', name, *jobs])
    if check.returncode:
        raise SystemExit(check.returncode)
start = time.time()
command = ['python3', 'tests/gates_test.py']
log = out / 'gates-test-final.log'
with log.open('w') as output:
    result = subprocess.run(command, env=env, stdout=output, stderr=subprocess.STDOUT)
(out / 'gates-test-final.json').write_text(json.dumps(dict(command=command,
    start=start, end=time.time(), exit=result.returncode,
    affinity=sorted(os.sched_getaffinity(0)), environment={'LANG':env['LANG'], 'LC_ALL':'unset'},
    source_sha256=hashlib.sha256((ROOT / 'tests/gates_test.py').read_bytes()).hexdigest(),
    log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()), indent=2) + '\n')
print('standalone harness', result.returncode, flush=True)

copy = ROOT / 'build/wave7/selftest-source-final'
assert not copy.exists(), 'retain the previous complete invocation; use a new copy for another retry'
for name in ('tests', 'tools', '.githooks', 'src'):
    shutil.copytree(ROOT / name, copy / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
for path in [ROOT / 'Makefile', ROOT / '.gitignore', *ROOT.glob('*.md')]:
    shutil.copy2(path, copy / path.name)
for name in ('docs/CONFIGURATION.md', 'docs/cd13b/audit.json', 'docs/dispatchfix/pre-sha256.txt',
             'docs/flakeaudit2/triage.json', 'docs/lbplanner/generic-cells.txt', 'docs/lbplanner/multidb-cells.txt'):
    (copy / name).parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / name, copy / name)
gate = (ROOT / 'tests/gate.sh').read_text()
adjusted = re.sub(r'^EXPECT_QUICK=768$', 'EXPECT_QUICK=798', gate, flags=re.M)
adjusted = re.sub(r'^EXPECT_FULL=785\b', 'EXPECT_FULL=815', adjusted, flags=re.M)
assert adjusted != gate
(copy / 'tests/gate.sh').write_text(adjusted)
(ROOT / 'docs/wave7/selftest-copy-final.json').write_text(json.dumps(dict(
    source_sha256=hashlib.sha256(gate.encode()).hexdigest(),
    copied_sha256=hashlib.sha256(adjusted.encode()).hexdigest(),
    harness_sha256=hashlib.sha256((copy / 'tests/gates_test.py').read_bytes()).hexdigest(),
    diff=''.join(difflib.unified_diff(gate.splitlines(True), adjusted.splitlines(True),
                                    fromfile='protected gate', tofile='throwaway gate'))), indent=2) + '\n')
abba = subprocess.run(['python3', 'docs/wave7/run_jobs.py', 'abba-selftest-final', 'abba_selftest',
                       '--selftest', '--root', str(copy)])
configuration = subprocess.run(['python3', 'docs/wave7/run_jobs.py',
                                'config-unit-final', 'config_unit'])
raise SystemExit(int(bool(result.returncode or abba.returncode or configuration.returncode)))
