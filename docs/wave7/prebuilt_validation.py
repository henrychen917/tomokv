#!/usr/bin/env python3
"""Require the complete WATCH job to reject the frozen prebuilt-spec defect."""
import ast
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
p = argparse.ArgumentParser()
p.add_argument('--spare-slot', action='store_true', help='64-71 server, 72-79 client, ports 26890-26898')
p.add_argument('--name', default='prebuilt-watch-negative-final')
args = p.parse_args()
allocation = ['--server-cores', '64-71', '--load-cores', '72-79', '--ports', '26890-26898'] if args.spare_slot else []
name = args.name
result = subprocess.run(['python3', 'docs/wave7/run_jobs.py', name,
    'datafix2_watch', '--binary', 'build/tomokv-wave7-before-prebuiltfix', *allocation])
receipt = json.loads((ROOT / 'docs/wave7/correctness' / name / 'receipt.json').read_text())
assert result.returncode == receipt['exit'] == 1
logs = sorted((Path(receipt['run_dir']) / 'jobs/datafix2_watch').glob('watch-*.log'))
assert len(logs) == 24
legs = []
for log in logs:
    text = log.read_text()
    assert 'ORACLE {' in text and 'GEOMETRY ' in text, log
    probes = [ast.literal_eval(line.removeprefix('PREBUILT '))
              for line in text.splitlines() if line.startswith('PREBUILT ')]
    target = [probe for probe in probes if probe['target']]
    assert target, log
    fused = '-1s-' in log.name
    if fused:
        assert 'Traceback (most recent call last)' in text and 'Aborted' in text, log
        assert 'PASS watch\n' not in text, log
        assert all(probe['writer_io'] != probe['owner'] for probe in target), log
    else:
        assert text.rstrip().endswith('PASS watch'), log
    legs.append(dict(leg=log.name, prebuilt_path=fused,
                     expected_failure=fused, target_cases_reached=target))
out = dict(expected_gate_exit=1, actual_gate_exit=result.returncode,
           broken_binary_sha256=receipt['binary_sha256'],
           fixed_binary_sha256=hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest(),
           helper_sha256=hashlib.sha256((ROOT / 'tests/wave7.py').read_bytes()).hexdigest(),
           fused_failures=sum(row['expected_failure'] for row in legs),
           split_passes=sum(not row['expected_failure'] for row in legs), legs=legs)
(ROOT / 'docs/wave7/prebuilt-watch-negative.json').write_text(json.dumps(out, indent=2) + '\n')
print('PASS: frozen defect fails all 16 fused legs; all 8 split controls pass', flush=True)
