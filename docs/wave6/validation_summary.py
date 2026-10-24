#!/usr/bin/env python3
"""Audit final whole-job receipts without treating a partial gate as a full receipt."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/wave6/correctness'
parser = argparse.ArgumentParser()
parser.add_argument('--require-complete', action='store_true')
args = parser.parse_args()
names = ['broad-final', 'integration-fixtures-final', 'tailgen-build',
         'abba-selftest-final', 'differ-uring', 'differ-epoll',
         'txnorder-round-2', 'txnorder-round-3', 'legacy-split-final',
         'legacy-fused', 'perfio-quiet', 'atomic-split-quiet', 'atomic-fused-quiet']
digest = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
manifest = json.loads((ROOT / 'docs/wave6/job-manifest.json').read_text())
excluded = {'efficiency', 'flip_saturated', 'atomic_floor'}
unavailable = {'tailgen_build': 'Build-only prerequisite explicitly refused by GATE_ONLY_JOBS; its full-gate-only load-generator consumer is reserved to the maintainer.'}
required = set(manifest['available']) - excluded - set(unavailable)
completed = defaultdict(list)
summary = []
problems = []
for name in names:
    path = OUT / name / 'receipt.json'
    if not path.exists():
        summary.append(dict(name=name, status='PENDING'))
        continue
    receipt = json.loads(path.read_text())
    if 'exit' not in receipt:
        summary.append(dict(name=name, status='RUNNING'))
        continue
    assert receipt['binary_sha256'] == receipt['binary_sha256_after'] == digest, name
    assert receipt['netfix_tls_oracle'].startswith('unset:'), name
    assert 'NETFIX_TLS_ORACLE' not in receipt['environment'], name
    if name == 'tailgen-build':
        assert receipt['exit'] == 2 and not receipt['jobs']
        assert 'tailgen_build is a build-only prerequisite; select its consuming correctness job' in (path.parent / 'gate.log').read_text()
        summary.append(dict(name=name, status='NOT RUN: interface refusal',
                            exit=receipt['exit'], receipt=str(path.relative_to(ROOT))))
        continue
    jobs = receipt['jobs']
    assert not excluded & set(jobs), name
    counts = Counter()
    failed = []
    for job, data in jobs.items():
        done = data['done'].split() if data['done'] else []
        if len(done) != 3 or done[0] != '0' or done[2] != '0':
            failed.append(job)
            continue
        counts['rows'] += int(done[1])
        completed[job].append(name)
    if receipt['exit'] or failed:
        problems.append(dict(suite=name, exit=receipt['exit'], jobs=failed))
    summary.append(dict(name=name, status='FAIL' if receipt['exit'] or failed else 'PASS',
                        jobs=len(jobs), passing_rows=counts['rows'],
                        seconds=round(receipt['end'] - receipt['start'], 2),
                        receipt=str(path.relative_to(ROOT))))

pending = [row['name'] for row in summary if row['status'] in ('PENDING', 'RUNNING')]
standalone_path = OUT / 'gates-test-final.json'
standalone = json.loads(standalone_path.read_text()) if standalone_path.exists() else None
if standalone and standalone['exit']:
    problems.append(dict(suite='gates-test-final', exit=standalone['exit']))
missing = sorted(required - set(completed))
txn = {job: completed[job] for job in manifest['available'] if job.startswith('txnorder-')}
coverage = json.loads((ROOT / 'docs/wave6/coverage.json').read_text())
result = dict(candidate_sha256=digest,
    scope='Whole correctness jobs through GATE_ONLY_JOBS; NOT a full gate/landing receipt.',
    suites=summary, standalone=standalone, problems=problems, pending=pending,
    available_jobs=len(manifest['available']), required_correctness_jobs=len(required),
    completed_unique_jobs=len(set(completed) & required), missing_jobs=missing,
    excluded_performance_jobs=sorted(excluded),
    unavailable_jobs=unavailable,
    txnorder_repetitions=txn, job_receipts=dict(sorted(completed.items())),
    touched_test_files=len(coverage['touched']),
    matched_protocol_literals=len(coverage['protocol_sweep']))
if args.require_complete:
    assert not pending and not problems and not missing, result
    assert standalone and standalone['exit'] == 0, 'standalone gates_test.py incomplete'
    assert all(len(runs) >= 3 for runs in txn.values()) and len(txn) == 4, txn
    for engine in ('uring', 'epoll'):
        receipt = json.loads((OUT / ('differ-' + engine) / 'receipt.json').read_text())
        assert receipt['environment']['GATE_DIFFER_NET_IO'] == engine
        assert set(manifest['differential']) <= set(receipt['jobs'])
    for name in ('legacy-fused', 'atomic-fused-quiet'):
        receipt = json.loads((OUT / name / 'receipt.json').read_text())
        assert receipt['environment']['GATE_TXN_FUSED'] == '1'
    result['complete'] = True
else:
    result['complete'] = not pending and not problems and not missing and bool(standalone)
(OUT / 'summary-final.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: result[k] for k in ('complete', 'completed_unique_jobs',
      'required_correctness_jobs', 'pending', 'problems', 'missing_jobs')}, indent=2))
