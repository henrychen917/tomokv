#!/usr/bin/env python3
"""Summarize immutable whole-job receipts without hiding failed attempts."""
import json
from pathlib import Path
import re

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
        resolved = path.stem == 'final-lanes' and label in resolved_labels
        failed.append(dict(label=label, resolved_by=str(repair_path.relative_to(ROOT)) if resolved else None))
        if not resolved:
            failures.append(dict(receipt=str(path.relative_to(ROOT)), label=label))
    assert len(failed) == int(match[2]), path
    rows.append(dict(name=path.stem, exit=receipt['exit'], passed=int(match[1]), failed=int(match[2]),
                     failures=failed, binary_sha256=receipt['binary_sha256'],
                     jobs=receipt['env']['GATE_ONLY_JOBS'], seconds=receipt['seconds'],
                     receipt=str(path.relative_to(ROOT)), artifacts=receipt['artifacts']))

gates = json.loads((OUT / 'gates-test-final.json').read_text())
build = json.loads((OUT / 'build/receipt.json').read_text())
assert gates['exit'] == 0
assert build['after_sha256'] == arms['POST']['sha256']
assert all(row['exit'] == 0 for row in build['builds'] + build['freshness'])
assert len(rows) >= 21, 'campaign is incomplete'
result = dict(post_sha256=arms['POST']['sha256'], runtime_identity_bridge='docs/wave8b/comment-sync.json',
              whole_job_invocations=len(rows), successful_row_executions=sum(r['passed'] for r in rows),
              failed_attempt_rows=sum(r['failed'] for r in rows), unresolved_failures=failures,
              rows=rows, gates_test=gates, make_freshness_checks=len(build['freshness']),
              not_run=['Full gate iteration and performance/load-generator merit: maintainer reserved'],
              dq=1, df=1, wave8_dq=8, wave8_df=8, expected_after_landing={'quick':807,'full':824})
(OUT / 'proof-summary.json').write_text(json.dumps(result, indent=2) + '\n')
lines = ['# Wave8b correctness evidence', '',
         'Whole jobs use the gate partial-job interface. Row executions include repeated prerequisites; this is not a full-gate receipt.', '',
         '| Invocation | Passing rows | Failed attempt rows | Result |', '|---|---:|---:|---|']
for row in rows:
    status = 'PASS' if row['exit'] == 0 else ('source checks repaired' if all(f['resolved_by'] for f in row['failures']) and row['failures'] else 'FAIL')
    lines.append(f"| [{row['name']}]({row['receipt'].removeprefix('docs/wave8b/')}) | {row['passed']} | {row['failed']} | {status} |")
lines += ['', f"Standalone gates_test exit: {gates['exit']}. Make freshness: {len(build['freshness'])}/{len(build['freshness'])}.", '',
          'The pre-comment and final POST binaries have identical runtime sections, program headers, entry point and symbols; only non-runtime debug/linker metadata and GNU build-id may differ. See comment-sync.json.', '',
          'The original three source-check failures remain in final-lanes. The final-source-repair job reruns their complete owning jobs.', '',
          'NOT RUN: performance benchmarks, load generators and the full gate iteration are reserved to the maintainer.']
(OUT / 'proof-summary.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({k:v for k,v in result.items() if k not in ('rows','gates_test')}), flush=True)
assert not failures, failures
