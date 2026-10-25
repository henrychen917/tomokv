#!/usr/bin/env python3
"""Repeat the complete gate-owned campaign on the corrected final executable."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
manifest = json.loads((ROOT / 'docs/wave7/job-manifest.json').read_text())
out = ROOT / 'docs/wave7/correctness/sequence-postfix.json'
binary = ROOT / 'build/tomokv'
digest = hashlib.sha256(binary.read_bytes()).hexdigest()
results = []

def run(name, command):
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest
    result = subprocess.run(command)
    results.append(dict(name=name, command=command, exit=result.returncode,
                        candidate_sha256=digest))
    out.write_text(json.dumps(results, indent=2) + '\n')
    print(name, result.returncode, flush=True)
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == digest

def job(name, jobs, *options):
    run(name, ['python3', 'docs/wave7/run_jobs.py', name, *jobs, *options])

job('merged-sweep-postfix', manifest['lanes'] + manifest['remaining'])
for engine in ('uring', 'epoll'):
    job('differ-postfix-' + engine, manifest['differential'], '--engine', engine)
cells = ['txnorder-fused-0', 'txnorder-fused-1', 'txnorder-split-0', 'txnorder-split-1']
for index in (2, 3):
    job('txnorder-postfix-' + str(index), cells)
legacy = ['release_batteries', 'notify', 'sort', 'script_bounds', 'dump_restore',
          'auth', 'replyoff', 'zc', 'aof-epoll', 'aof-uring', 'snapshot-epoll',
          'snapshot-uring', 'aof_frame', 'debug-0', 'debug-1', 'asan_batteries']
job('legacy-fused-postfix', legacy, '--fused')
for index in (1, 2, 3):
    job('persistence-errors-postfix-' + str(index), ['persistfix2_errors'])
run('production-build-postfix', ['python3', 'docs/wave7/production_build.py'])
# Keep all compilation and other live jobs out of the scheduler/latency checks.
run('harness-final', ['python3', 'docs/wave7/harness_retry.py', '--harness-only'])
job('perfio-quiet-postfix', ['perfio_stream'])
run('watch-final-controls', ['python3', 'docs/wave7/watch_validation.py'])
raise SystemExit(int(any(row['exit'] for row in results)))
