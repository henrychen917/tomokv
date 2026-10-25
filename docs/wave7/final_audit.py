#!/usr/bin/env python3
"""Check final evidence bindings and completeness without running any server."""
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
DOC = ROOT / 'docs/wave7'
def read(name):
    return json.loads((DOC / name).read_text())
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

post = sha(ROOT / 'build/tomokv')
pad = read('pad-a.json')
assert pad['arms']['POST']['sha256'] == post
assert pad['arms']['PAD-A']['sha256'] == sha(ROOT / 'build/tomokv-wave7-PAD-A')
assert pad['post_text'] == pad['pad_text']
fix = read('prebuilt-fix-identity.json')
assert fix['after_sha256'] == post and len(fix['changed']) == 4
assert fix['before_sha256'] == sha(ROOT / 'build/tomokv-wave7-before-prebuiltfix')
assert read('instructions/provenance.json')['links']['post-production']['sha256'] == post
instructions = read('instructions/comparison.json')
plain = [row for row in instructions if row['command'] in ('GET', 'SET', 'INCR')]
assert len(instructions) == 80 and len(plain) == 48
assert all(row['delta'] <= 0 and not row['post_watch_functions'] for row in plain)
assert all(row['external_library_call_counts_equal'] for row in instructions)

gate = (ROOT / 'tests/gate.sh').read_text()
baseline = subprocess.check_output(['git', 'show', '05a5e01a9:tests/gate.sh'], text=True)
for name in ('EXPECT_QUICK', 'EXPECT_FULL'):
    assert re.search(r'^' + name + r'=.*$', gate, re.M)[0] == re.search(r'^' + name + r'=.*$', baseline, re.M)[0]
rows = read('rows.json')
assert rows['required'] == [798, 815] and rows['fixture'] == 815
assert rows['DQ'] == rows['DF'] == 30
assert rows['gate_sha256'] == sha(ROOT / 'tests/gate.sh')
inventory = read('r7-inventory/summary.json')
merged = next(row for row in inventory if row['arm'] == 'merged')
assert merged['counts'] == {'tomo': 156, 'tomo_db0': 156} and merged['sha256'] == post

summary = read('correctness/summary.json')
assert not summary['pending'] and summary['post_sha256'] == post
coverage = read('coverage-results.json')
assert coverage['post_sha256'] == post and not coverage['unresolved_functions']
jobs = coverage['jobs']
passing = [name for name, row in jobs.items() if row['status'] == 'PASS']
assert len(passing) == 215, [(name, row['status']) for name, row in jobs.items() if row['status'] != 'PASS']
assert all(count >= 3 for count in coverage['transaction_successful_runs'].values())
assert jobs['tailgen_build']['status'].startswith('COMPILE ONLY:')
for name in read('job-manifest.json')['reserved']:
    assert jobs[name]['status'].startswith('NOT RUN:')
for name in ('merged-sweep-postfix', 'differ-postfix-uring', 'differ-postfix-epoll',
             'txnorder-postfix-2', 'txnorder-postfix-3', 'legacy-fused-postfix',
             'abba-selftest-final', 'perfio-quiet-postfix'):
    receipt = read('correctness/' + name + '/receipt.json')
    assert receipt['exit'] == 0 and receipt['binary_sha256'] == receipt['binary_sha256_after'] == post, name
    assert receipt['environment']['LANG'] == 'en_US.UTF-8' and 'LC_ALL' not in receipt['environment']

watch_legs = []
for index in (1, 2, 3):
    name = 'watch-final-' + str(index)
    receipt = read('correctness/' + name + '/receipt.json')
    assert receipt['exit'] == 0 and receipt['binary_sha256'] == post
    logs = sorted((Path(receipt['run_dir']) / 'jobs/datafix2_watch').glob('watch-*.log'))
    assert len(logs) == 24
    for log in logs:
        body = log.read_text()
        assert body.rstrip().endswith('PASS watch')
        results = [ast.literal_eval(line.split('forms ', 1)[1])
                   for line in body.splitlines() if line.startswith('PASS wave7 prebuilt SET WATCH forms ')]
        assert len(results) == 2 and all(row['cases'] == 30 for row in results)
        target = next(row for row in results if row['target'])
        assert len(set(target['writer_ios'])) == 2
        watch_legs.append(dict(selection=name, leg=log.name, cases=target['cases'],
                               writer_ios=target['writer_ios']))
negative = read('prebuilt-watch-negative.json')
assert negative['fixed_binary_sha256'] == post
assert negative['fused_failures'] == 16 and negative['split_passes'] == 8
assert negative['helper_sha256'] == sha(ROOT / 'tests/wave7.py')
window = read('watch-window-negative.json')
assert window['candidate_sha256'] == post and len(window['legs']) == 24
assert all(row['missing_window_rejected'] for row in window['legs'])

harness = read('correctness/gates-test-final.json')
assert harness['exit'] == 0
assert harness['source_sha256'] == sha(ROOT / 'tests/gates_test.py')
assert harness['log_sha256'] == sha(DOC / 'correctness/gates-test-final.log')
assert 'Ran 72 tests' in (DOC / 'correctness/gates-test-final.log').read_text()
copy = read('selftest-copy-final.json')
assert copy['source_sha256'] == sha(ROOT / 'tests/gate.sh')
assert copy['harness_sha256'] == sha(ROOT / 'tests/gates_test.py')
build = read('build/receipt.json')
assert build['before_sha256'] == build['after_sha256'] == post
assert len(build['freshness']) == 46
assert all(row['exit'] == 0 for row in build['builds'] + build['freshness'])
lean = read('lean-build.json')
assert lean['protected_before'] == lean['protected_after']
assert lean['protected_after']['build/tomokv'] == post
assert all(row['exit'] == 0 for row in lean['freshness'])

result = dict(post_sha256=post, pad_sha256=pad['arms']['PAD-A']['sha256'],
              passing_gate_jobs=len(passing), rows=rows['required'],
              transaction_successful_runs=coverage['transaction_successful_runs'],
              plain_zero_added_cells=len(plain), command_scope_cells=len(instructions),
              watch_complete_jobs=3, watch_legs=watch_legs,
              broken_prebuilt_fused_failures=16, broken_prebuilt_split_passes=8,
              absent_eviction_window_rejections=24, standalone_harness_tests=72,
              production_freshness_checks=46, build_bytes_saved=lean['bytes_saved'])
(DOC / 'final-audit.json').write_text(json.dumps(result, indent=2) + '\n')
print('PASS final evidence: 215 gate jobs, 80 instruction cells, controls, builds and protected counts')
