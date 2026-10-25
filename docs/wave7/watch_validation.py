#!/usr/bin/env python3
"""Whole WATCH-table jobs plus a target-only missing-eviction-window control."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
for index in range(1, 4):
    subprocess.run(['python3', 'docs/wave7/run_jobs.py', f'watch-final-{index}',
                    'datafix2_watch'], check=True)

source = ROOT / 'build/wave7/selftest-source-final'
copy = ROOT / 'build/wave7/watch-negative-source'
assert source.exists() and not copy.exists()
shutil.copytree(source, copy, ignore=shutil.ignore_patterns('build', '__pycache__', '*.pyc'))
original = (ROOT / 'tests/datafix2_watch.py').read_text()
needle = 'c.cmd("CONFIG","SET","maxmemory-policy","allkeys-lru")'
replacement = 'c.cmd("CONFIG","SET","maxmemory-policy", "noeviction" if (c.host,c.port) == TARGET else "allkeys-lru")'
assert original.count(needle) == 1
planted = original.replace(needle, replacement)
(copy / 'tests/datafix2_watch.py').write_text(planted)
result = subprocess.run(['python3', 'docs/wave7/run_jobs.py', 'watch-window-negative',
                         'datafix2_watch', '--root', str(copy)])
receipt = json.loads((ROOT / 'docs/wave7/correctness/watch-window-negative/receipt.json').read_text())
run = Path(receipt['run_dir']) / 'jobs/datafix2_watch'
logs = sorted(run.glob('watch-*.log'))
assert len(logs) == 24, len(logs)
observed = []
for log in logs:
    text = log.read_text()
    assert 'ORACLE {' in text and 'GEOMETRY ' in text, log
    assert 'AssertionError: eviction window never opened on three fresh cohorts' in text, log
    attempts = [json.loads(line[len('EVICTION '):]) for line in text.splitlines()
                if line.startswith('EVICTION {')]
    target_attempts = [value for value in attempts if value['remaining'] == 128]
    assert len(target_attempts) == 3, (log, target_attempts)
    assert all(value['pulses'] == 32 and value['seeded'] == 128
               and not value['seed_errors'] for value in target_attempts), log
    observed.append(dict(leg=log.name, missing_window_rejected=True,
                         fresh_cohorts=3, bounded_pressure_writes=96))
assert result.returncode == 1, result.returncode
assert receipt['jobs']['datafix2_watch']['done'].split() == ['0','0','1']
(ROOT / 'docs/wave7/watch-window-negative.json').write_text(json.dumps(dict(
    expected_gate_exit=1, actual_gate_exit=result.returncode,
    source_sha256=hashlib.sha256(original.encode()).hexdigest(),
    planted_sha256=hashlib.sha256(planted.encode()).hexdigest(),
    only_helper_change=dict(before=needle, after=replacement),
    inherited_gate_count_edit='throwaway self-test copy only: 798/815',
    candidate_sha256=receipt['binary_sha256'], legs=observed), indent=2) + '\n')
print('PASS: all 24 target legs reject the deliberately absent eviction window', flush=True)
