#!/usr/bin/env python3
"""Join immutable gate receipts without converting a missing/failed leg to PASS."""
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave5'
sys.path.insert(0, str(ROOT / 'tests'))
from gate_history import canonical_label

COHORTS = '''correctness-landing differ-uring differ-epoll supplement-epoll
supplement-fused-uring supplement-fused-epoll bounded-uring bounded-epoll
bounded-fused-uring bounded-fused-epoll abba-quiet'''.split()
sha = hashlib.sha256((ROOT / 'build/tomokv').read_bytes()).hexdigest()
cohorts, all_rows, per_job = [], [], defaultdict(Counter)
for name in COHORTS:
    directory = DOC / 'gate' / name
    receipt = json.loads((directory / 'result.json').read_text())
    assert receipt['returncode'] == 0, (name, receipt['returncode'])
    assert receipt['binary_stable'] and receipt['binary_sha256'] == sha, name
    if not (directory / 'rows.json').exists():
        subprocess.run([sys.executable, str(DOC / 'archive_gate.py'), name], check=True)
    rows = json.loads((directory / 'rows.json').read_text())
    assert rows and all(row['verdict'] == 'ok' for row in rows), name
    counts = defaultdict(Counter)
    for row in rows:
        label = canonical_label(row['label'])
        counts[row['job']][label] += 1
        all_rows.append(dict(cohort=name, **row))
    for job, labels in counts.items():
        per_job[job] |= labels
    cohorts.append(dict(name=name, rows=len(rows), jobs=sorted(counts),
                        elapsed=receipt['elapsed'], sha256=receipt['binary_sha256']))

observed = sum(per_job.values(), Counter())
fixture = Counter(json.loads((ROOT / 'tests/fixtures/nullrefresh-ledger-labels.json').read_text())['labels'])
missing = fixture - observed
represented = {}
for geometry, label in (
        ('split', 'Redis 7.4 differential matrix'),
        ('armed', 'Redis 7.4 differential matrix (armed fused + read-local)')):
    # Partial-job mode emits the two atomic-part labels instead of the full
    # coordinator's aggregate label. Preserve that distinction in the receipt.
    parts = [f'differ-{geometry}-{atomic}' for atomic in (0, 1)]
    assert all(part in per_job for part in parts), parts
    if label in missing:
        represented[label] = dict(parts=parts, engines=['uring', 'epoll'])
not_run = missing - Counter(represented.keys())
reserved = Counter([
    'expire-index growth bound', 'borrow-registry growth bound',
    'cross-shard dispatch scaling', 'atomic MGET/MSET floor (N/s >= 120k)',
    'tripwire arm/disarm round-trip', 'pipelined same-conn program order (400 rolls)',
    'tailgen client-lb outstanding bound',
])
assert not_run == reserved, ('unexplained missing or extra fixture coverage', not_run, reserved)
inventory = json.loads((DOC / 'row-inventory.json').read_text())
lanes = []
for lane in inventory['lanes']:
    added = Counter(lane['full']['added'])
    assert not added - observed, (lane['lane'], added - observed)
    lanes.append(dict(lane=lane['lane'], added_rows=sum(added.values()),
                      passing_labels=dict(added)))

result = dict(binary_sha256=sha, cohorts=cohorts,
              passed_observations=len(all_rows), distinct_jobs=len(per_job),
              declared_fixture_rows=sum(fixture.values()),
              covered_fixture_rows=sum((fixture & observed).values()),
              fixture_labels_without_literal_row=dict(missing),
              aggregate_labels_represented_by_parts=represented,
              not_run_fixture_labels=dict(not_run),
              lane_added_rows=lanes,
              note='Repeated mode/engine cohorts are observations, not new gate rows. '
                   'Per-job label multiplicity uses the maximum observed in one cohort. '
                   'Performance rows remain with the maintainer.')
(DOC / 'final-correctness.json').write_text(json.dumps(result, indent=2) + '\n')
(DOC / 'final-rows.json').write_text(json.dumps(all_rows, indent=2) + '\n')
print(json.dumps(result, indent=2))
