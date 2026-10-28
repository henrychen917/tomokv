#!/usr/bin/env python3
"""Map each requested whole job and added label to its retained final-arm verdict."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave9'
matrix = json.loads((DOC / 'correctness-matrix.json').read_text())
evidence = {x['name']: x for x in json.loads((DOC / 'job-evidence-index.json').read_text())}
# Read the recorded arm, rather than trusting a current executable path.
post_sha = json.loads((DOC / 'jobs/final-once.json').read_text())['binary_sha256']
overrides = {name: 'repair-rechecks' for name in
             ('reorder_bounds', 'at412-T1', 'at412-T5', 'at412-T12', 'exbatch_units')}
overrides.update({name: 'atomic-recheck2' for name in ('atomic_units', 'at412-owner')})
rows = []


def add(campaign, job, group):
    entry = evidence.get(campaign)
    # Differential collectors fold these exact complete child jobs.
    names = ({'differ-split': ['differ-split-0', 'differ-split-1', 'differ-equivalence'],
              'differ-armed': ['differ-armed-0', 'differ-armed-1']}).get(job, [job])
    found = [x for x in (entry or {}).get('jobs', []) if x['name'] in names]
    status = 'NOT RUN'
    if entry and len(found) == len(names):
        status = 'PASS' if all(x['done'] and x['done'].split()[0] == '0' and
                               x['done'].split()[2] == '0' for x in found) else 'FAIL'
        if group != 'selftest_throwaway':
            assert entry['binary_sha256'] == post_sha, (campaign, 'not final POST')
    rows.append(dict(group=group, campaign=campaign, job=job, status=status,
                     children=[dict(name=x['name'], done=x['done'], rows=x['rows']) for x in found]))


for name in matrix['once']:
    add(overrides.get(name, 'final-once'), name, 'once')
for key, campaign in [('supplemental_once', 'supplemental-once'), ('additional_once', 'final-additional')]:
    for name in matrix[key]:
        add(campaign, name, key)
for mode in ('1s', '2s'):
    for name in matrix['each_mode']:
        add('final-persistence-' + mode, name, 'each_mode/' + mode)
for engine in ('uring', 'epoll'):
    for key, prefix in [('differ_each_engine', 'final-differ-'), ('each_engine', 'final-engine-')]:
        for name in matrix[key]:
            add(prefix + engine, name, key + '/' + engine)
    for mode in ('1s', '2s'):
        for name in matrix['each_mode_engine']:
            add('final-mode-' + engine + '-' + mode, name, 'each_mode_engine/' + engine + '/' + mode)
add('execfair-loaded', 'execfair', 'deliberately_loaded')
add('final-tcl', 'redis_tcl', 'tcl_both_modes')
add('final-tcl', 'compat2', 'tcl_dependency_and_native_legs')
add('final-selftest4', 'abba_selftest', 'selftest_throwaway')

labels = collections.defaultdict(list)
for row in rows:
    for job in row['children']:
        for item in job['rows']:
            if item['verdict'] == 'ok':
                labels[item['label']].append(dict(campaign=row['campaign'], job=job['name']))
added = []
for lane in json.loads((DOC / 'new-row-labels.json').read_text()):
    for job in lane['rows']:
        for label in job['labels']:
            added.append(dict(lane=lane['lane'], label=label, passing_receipts=labels.get(label, [])))
assert len(added) == 74
out = dict(post_sha256=post_sha, job_invocations=rows, added_rows=added,
           summary=dict(collections.Counter(row['status'] for row in rows)),
           new_rows_passing=sum(bool(row['passing_receipts']) for row in added),
           note='Whole-job verdicts; repeated prerequisite/public rows are not summed into a landing gate count.')
(DOC / 'coverage.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps({k: v for k, v in out.items() if k not in ('job_invocations', 'added_rows')}))
