#!/usr/bin/env python3
"""Summarize immutable whole-job receipts without hiding failed attempts."""
import json
from pathlib import Path
import re
from run_final import campaign

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/wave8b'
arms = json.loads((OUT / 'arms.json').read_text())
bridge = json.loads((OUT / 'comment-sync.json').read_text())
assert bridge['identical'] and bridge['after']['sha256'] == arms['POST']['sha256']
accepted = {bridge['before']['sha256'], bridge['after']['sha256']}
repair_path = OUT / 'jobs/final-source-repair.json'
repair = json.loads(repair_path.read_text())
assert repair['exit'] == 0 and repair['binary_unchanged']
repair_rows = {}
for ledger in (Path(repair['artifacts']) / 'jobs').glob('*/ledger'):
    for line in ledger.read_text().splitlines():
        status, seconds, label = line.split('\t', 2)
        repair_rows[label] = status
resolved_labels = {
    'R7 generated envelope parity',
    'splitlocal template forwarding + old-argument controls',
    'writeback policy clauses witnesses + negative controls',
}
assert all(repair_rows.get(label) == 'ok' for label in resolved_labels)
selftest_setup = json.loads((OUT / 'selftest-setup-error.json').read_text())
assert selftest_setup['invalid_setup'] and selftest_setup['actual_counts'] == {'quick':807,'full':815}
selftest_repair_path = ROOT / selftest_setup['required_repair_receipt']
selftest_repair = json.loads(selftest_repair_path.read_text())
assert selftest_repair['exit'] == 0 and selftest_repair['binary_unchanged']
assert selftest_repair['env']['GATE_ONLY_JOBS'] == 'abba_selftest'
selftest_copy = json.loads((OUT / 'selftest-copy-count-repair.json').read_text())
assert selftest_copy['counts'] == {'quick':807,'full':824}
assert selftest_copy['copy_gate_sha256'] == selftest_repair['gate_sha256']
rows, failures = [], []
for path in sorted((OUT / 'jobs').glob('final-*.json')):
    receipt = json.loads(path.read_text())
    assert receipt['binary_sha256'] in accepted and receipt['binary_unchanged'], path
    summary, = receipt['summary']
    match = re.search(r'GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL', summary)
    assert match, summary
    failed = []
    ledger = Path(receipt['env']['GATE_LEDGER'] + '.partial')
    for line in ledger.read_text().splitlines():
        if not line.startswith('FAIL\t'):
            continue
        _, seconds, label = line.split('\t', 2)
        resolved_by = None
        if path.stem == 'final-lanes' and label in resolved_labels:
            resolved_by = str(repair_path.relative_to(ROOT))
        if path.stem == 'final-abba-selftest' and label == 'ABBA comparison + saturation negative controls':
            resolved_by = str(selftest_repair_path.relative_to(ROOT))
        resolved = resolved_by is not None
        failed.append(dict(label=label, resolved_by=resolved_by))
        if not resolved:
            failures.append(dict(receipt=str(path.relative_to(ROOT)), label=label))
    assert len(failed) == int(match[2]), path
    if receipt['exit'] != 0 and not failed:
        failures.append(dict(receipt=str(path.relative_to(ROOT)),
                             label='nonzero invocation exit without a failed-row verdict'))
    if failed:
        assert receipt['exit'] != 0, 'failed rows with a successful invocation exit'
    rows.append(dict(name=path.stem, exit=receipt['exit'], passed=int(match[1]), failed=int(match[2]),
                     failures=failed, binary_sha256=receipt['binary_sha256'],
                     invalid_setup=path.stem == 'final-abba-selftest',
                     jobs=receipt['env']['GATE_ONLY_JOBS'], seconds=receipt['seconds'],
                     receipt=str(path.relative_to(ROOT)), artifacts=receipt['artifacts']))

gates = json.loads((OUT / 'gates-test-final.json').read_text())
build = json.loads((OUT / 'build/receipt.json').read_text())
assert gates['exit'] == 0
assert build['after_sha256'] == arms['POST']['sha256']
assert all(row['exit'] == 0 for row in build['builds'] + build['freshness'])
required = {name for name, jobs, options in campaign} | {
    'final-source-repair', 'final-abba-selftest', 'final-abba-selftest-count-repair'}
assert required <= {row['name'] for row in rows}, 'campaign is incomplete'
assert len(build['freshness']) == 49
timing = json.loads((OUT / 'timing-interactions.json').read_text())
assert timing['binary_sha256'] in accepted
assert {(row['mode'], row['atomic'], row['engine']) for row in timing['rows']} == {
    (mode, atomic, engine) for mode in ('1s', '2s') for atomic in (0, 1)
    for engine in ('uring', 'epoll')}
controls = json.loads((OUT / 'controls/receipts.json').read_text())
assert {row['case'] for row in controls} == {'scan', 'stale', 'callback', 'orphan'}
assert all(row['exit'] == -6 for row in controls), 'planted native failures did not abort'
source_controls = json.loads((OUT / 'source-controls.json').read_text())
assert len(source_controls) == 22 and all(row['passed'] for row in source_controls)
result = dict(post_sha256=arms['POST']['sha256'], runtime_identity_bridge='docs/wave8b/comment-sync.json',
              whole_job_invocations=len(rows), successful_row_executions=sum(r['passed'] for r in rows if not r['invalid_setup']),
              failed_attempt_rows=sum(r['failed'] for r in rows), unresolved_failures=failures,
              invalid_setup_attempts=[r['name'] for r in rows if r['invalid_setup']],
              rows=rows, gates_test=gates, make_freshness_checks=len(build['freshness']),
              timing_interaction_legs=len(timing['rows']), native_negative_controls=len(controls),
              source_controls=len(source_controls),
              not_run=['Full gate iteration and performance/load-generator merit: maintainer reserved'],
              dq=1, df=1, wave8_dq=8, wave8_df=8, expected_after_landing={'quick':807,'full':824})
(OUT / 'proof-summary.json').write_text(json.dumps(result, indent=2) + '\n')
lines = ['# Wave8b correctness evidence', '',
         'Whole jobs use the gate partial-job interface. Row executions include repeated prerequisites; this is not a full-gate receipt.', '',
         '| Invocation | Passing rows | Failed attempt rows | Result |', '|---|---:|---:|---|']
for row in rows:
    status = 'setup repaired' if row['invalid_setup'] else ('PASS' if row['exit'] == 0 else (
        'source checks repaired' if all(f['resolved_by'] for f in row['failures']) and row['failures'] else 'FAIL'))
    lines.append(f"| [{row['name']}]({row['receipt'].removeprefix('docs/wave8b/')}) | {row['passed']} | {row['failed']} | {status} |")
lines += ['', f"Standalone gates_test exit: {gates['exit']}. Make freshness: {len(build['freshness'])}/{len(build['freshness'])}.", '',
          'The pre-comment and final POST binaries have identical runtime sections, program headers, entry point and symbols; only non-runtime debug/linker metadata and GNU build-id may differ. See comment-sync.json.', '',
          'The original three source-check failures remain in final-lanes. The final-source-repair job reruns their complete owning jobs.', '',
          'The initial ABBA self-test copy incorrectly retained EXPECT_FULL=815 because of its trailing comment. Its attempt is retained but is not accepted as proof. A new copy verifies 807/824 and reruns the whole job; see selftest-setup-error.json and selftest-copy-count-repair.json.', '',
          'NOT RUN: performance benchmarks, load generators and the full gate iteration are reserved to the maintainer.']
(OUT / 'proof-summary.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('rows','gates_test')}), flush=True)
assert not failures, failures
