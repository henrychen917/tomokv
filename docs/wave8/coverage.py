#!/usr/bin/env python3
"""Account for every requested whole-job/mode/engine binding and its receipt."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser()
p.add_argument('--allow-incomplete', action='store_true')
a = p.parse_args()
matrix = json.loads((ROOT / 'docs/wave8/correctness-matrix.json').read_text())
extra = json.loads((ROOT / 'docs/wave8/supplemental-matrix.json').read_text())
sha = json.loads((ROOT / 'docs/wave8/binaries.json').read_text())['POST']['sha256']
receipts = {}
for path in (ROOT / 'docs/wave8/jobs').glob('final-*.json'):
    data = json.loads(path.read_text())
    if data['binary_sha256'] == sha:
        assert data['binary_unchanged']
        receipts[path.stem] = data

expected = []
for job in dict.fromkeys(matrix['once'] + extra['once'] + matrix['tcl']):
    expected.append(dict(job=job))
for engine in ('uring', 'epoll'):
    for job in matrix['each_engine'] + extra['each_engine'] + matrix['differ_each_engine']:
        expected.append(dict(job=job, engine=engine))
    for mode in ('1s', '2s'):
        for job in matrix['each_mode_engine'] + extra['each_mode_engine']:
            expected.append(dict(job=job, engine=engine, mode=mode))
for mode in ('1s', '2s'):
    for job in extra['each_mode']:
        expected.append(dict(job=job, mode=mode))
expected.append(dict(job='abba_selftest'))

def job_passed(data, job):
    done = Path(data['artifacts']) / 'jobs' / job / 'done'
    if done.exists():
        rc, passed, failed = map(int, done.read_text().split())
        return rc == 0 and failed == 0
    # Public differential aliases fold several private jobs. Their complete
    # batch verdict is required; never infer a fold from one private child.
    assert job in ('differ-split', 'differ-armed'), (job, done)
    return data['exit'] == 0

for row in expected:
    matches = []
    for name, data in receipts.items():
        env = data['env']
        if row['job'] not in env['GATE_ONLY_JOBS'].split():
            continue
        if 'engine' in row and env['GATE_NET_IO'] != row['engine']:
            continue
        if 'mode' in row and env['GATE_TXN_FUSED'] != str(int(row['mode'] == '1s')):
            continue
        matches.append(name)
    row['receipts'] = matches
    row['passing_receipts'] = [n for n in matches if job_passed(receipts[n], row['job'])]
    row['status'] = ('PASS' if row['passing_receipts'] else 'FAILED JOB' if matches else 'NOT RUN')

result = dict(post_sha256=sha, bindings=expected,
              complete=all(row['receipts'] for row in expected),
              all_bindings_have_passing_receipt=all(row['status'] == 'PASS' for row in expected),
              note='Every failed attempt remains in the batch history; a job passes only with its own completed zero-failure receipt. This is selected-job coverage, not a full gate receipt.',
              batches={name: dict(exit=d['exit'], seconds=d['seconds'], summary=d['summary']) for name, d in receipts.items()})
(ROOT / 'docs/wave8/coverage.json').write_text(json.dumps(result, indent=2) + '\n')
print('Bindings:', len(expected), 'PASS:', sum(r['status'] == 'PASS' for r in expected),
      'FAILED JOB:', sum(r['status'] == 'FAILED JOB' for r in expected),
      'NOT RUN:', sum(r['status'] == 'NOT RUN' for r in expected))
if not a.allow_incomplete:
    assert result['complete'], 'required job bindings are missing'
    assert result['all_bindings_have_passing_receipt'], 'inspect failed whole-job receipts'
