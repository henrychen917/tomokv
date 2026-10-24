#!/usr/bin/env python3
"""Run all selected correctness jobs on the frozen final integration binary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, set(range(64, 96)))
os.environ.pop('NETFIX_TLS_ORACLE', None)
doc = ROOT / 'docs/wave6'
build = json.loads((doc / 'correctness/build-final.json').read_text())
digest = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
assert build['build_exit'] == 0 and all(x['exit'] == 0 for x in build['freshness'])
assert digest == build['binary_sha256']
counts = json.loads((doc / 'instructions/comparison-final.json').read_text())
assert len(counts) == 64
assert all(x['delta'] <= 0 for x in counts if x['command'] != 'MGET')
provenance = json.loads((doc / 'instructions/provenance.json').read_text())
assert provenance['links']['post-production']['sha256'] == digest
for namespace in ('normal', 'db0'):
    assert all(row['production_equal'] or row.get('verified_switch_equal', False)
               for row in provenance['post-' + namespace])
manifest = json.loads((doc / 'job-manifest.json').read_text())
jobs = list(dict.fromkeys(manifest['lanes'] + manifest['remaining']))
assert not {'efficiency', 'flip_saturated', 'atomic_floor'} & set(jobs)
result = subprocess.run(['python3', 'docs/wave6/run_jobs.py', 'broad-final', *jobs])
print('Final broad jobs exit:', result.returncode, flush=True)
broad_exit = result.returncode
# The subsequent sequence records failures independently and completes the
# differential, repeated txnorder, both-mode and quiet correctness coverage.
result = subprocess.run(['python3', 'docs/wave6/finish_jobs.py'])
print('Final remaining jobs exit:', result.returncode, flush=True)
assert hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest() == digest
raise SystemExit(int(bool(broad_exit or result.returncode)))
