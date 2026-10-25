#!/usr/bin/env python3
"""Resolve the test/token sweep to complete gate jobs and recorded verdicts."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
OUT = ROOT / 'docs/wave7'
manifest = json.loads((OUT / 'job-manifest.json').read_text())
coverage = json.loads((OUT / 'coverage.json').read_text())
summary = json.loads((OUT / 'correctness/summary.json').read_text())
available = set(manifest['available'])
aliases = {'feature_split_job': 'feature-split', 'feature_armed_job': 'feature-armed',
           'compat3_case': 'compat3'}

def resolve(function):
    # Scheduler helpers belong to the harness self-test and every dispatched
    # family. This is a conservative consumer mapping, not branch coverage.
    if function in {'job_body', 'job_dependencies', 'job_finalize', 'job_ready', 'job_recover'}:
        return sorted(available)
    name = aliases.get(function, function.removeprefix('job_'))
    if name in available:
        return [name]
    name = name.replace('_', '-')
    return sorted(job for job in available if job == name or job.startswith(name + '-'))

def passes(entry):
    return entry['current_post'] and not entry.get('diagnostic') and entry['exit'] == '0' and not entry['rows'].get('FAIL', 0)

jobs = {}
for name in sorted(available):
    entries = summary['jobs'].get(name, [])
    good = [entry for entry in entries if passes(entry)]
    status = 'PASS' if good else 'NOT COMPLETE'
    if name in manifest['reserved']:
        status = 'NOT RUN: ' + manifest['reserved'][name]
    elif name == 'tailgen_build' and not entries:
        status = 'COMPILE ONLY: build/tailgen is built by make all; no measurement generator runs'
    elif name.startswith('differ-') and {entry['engine'] for entry in good} != {'uring', 'epoll'}:
        status = 'NOT COMPLETE: both engines required'
    jobs[name] = dict(status=status, successful_selections=[entry['selection'] for entry in good],
                      invocations=entries)

unresolved = set()
for group in ('touched', 'protocol_sweep'):
    for item in coverage[group]:
        mapped = set()
        for function in item['jobs']:
            names = resolve(function)
            if not names:
                unresolved.add(function)
            mapped.update(names)
        item['gate_jobs'] = {name: jobs[name]['status'] for name in sorted(mapped)}

transaction = {name: sum(passes(entry) for entry in summary['jobs'].get(name, []))
               for name in ('txnorder-fused-0', 'txnorder-fused-1', 'txnorder-split-0', 'txnorder-split-1')}
result = dict(post_sha256=summary['post_sha256'], jobs=jobs, coverage=coverage,
              unresolved_functions=sorted(unresolved), transaction_successful_runs=transaction)
(OUT / 'coverage-results.json').write_text(json.dumps(result, indent=2) + '\n')
print('passing jobs', sum(value['status'] == 'PASS' for value in jobs.values()),
      'unresolved mappings', sorted(unresolved), 'transaction counts', transaction)
