#!/usr/bin/env python3
"""Account for every declared public row without turning failures into passes."""
from collections import Counter
import argparse
import json
import os
from pathlib import Path
import sys
import tarfile

from wave14 import ROOT, DOC, save, sha
from wave14_validation import phase, differential

sys.path.insert(0, str(ROOT / 'tests'))
from gate_ledger_fixture import source_labels


NOT_RUN = {
    'expire-index growth bound': 'The efficiency job requests release timing ratios.',
    'borrow-registry growth bound': 'The efficiency job requests release timing ratios.',
    'cross-shard dispatch scaling': 'Scaling/performance job reserved to the maintainer.',
    'FLIP applies under saturated load': 'Starts memtier; reserved to the maintainer.',
    'flip battery shutdown invariants': 'Shares the excluded saturated-FLIP boot.',
    'atomic MGET/MSET floor (N/s >= 120k)': 'Explicitly omitted by GATE_PROOF_NO_RATES=1.',
    'tailgen client-lb outstanding bound': 'Starts the open-loop tailgen driver; reserved to the maintainer.',
}


def ledger(text):
    return [dict(status=s, seconds=float(t), label=n)
            for s, t, n in (line.split('\t', 2) for line in text.splitlines())]


def main():
    assert os.sched_getaffinity(0) <= set(range(32))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--abba-tag', default='abba-landing-complete')
    args = parser.parse_args()
    primary = phase('merged-final-uring', True)
    assert primary['state'] == 'COMPLETE' and not primary['unfinished']
    expected = Counter(source_labels((ROOT / 'tests/gate.sh').read_text()))
    rows = [dict(row, job=job['job']) for job in primary['jobs'] for row in job['rows']]
    observed = Counter(row['label'] for row in rows)
    companions = json.loads((DOC / 'jobs/atomic-companions-final-uring.json').read_text())
    assert companions['exit_code'] == 0
    assert companions['binary_sha256'] == primary['binary_sha256']
    directory = Path(companions['run_directory']) / 'jobs/atomic_floor'
    additions = ledger((directory / 'ledger').read_text())
    observed.update(row['label'] for row in additions)
    abba = json.loads((DOC / 'jobs' / (args.abba_tag + '.json')).read_text())
    assert abba['exit_code'] == 0 and abba['binary_sha256'] == primary['binary_sha256']
    assert sha(abba['archive']) == abba['archive_sha256']
    with tarfile.open(abba['archive'], 'r:gz') as stored:
        abba_rows = ledger(stored.extractfile('jobs/abba_selftest/ledger').read().decode())
    observed.update(row['label'] for row in abba_rows)
    folds = differential([primary])
    assert len(folds) == 2 and all(row['evidence']['complete'] for row in folds)
    aggregate_labels = ['Redis 7.4 differential matrix',
                        'Redis 7.4 differential matrix (armed fused + read-local)']
    observed.update(aggregate_labels)
    missing = expected - observed
    assert missing == Counter(NOT_RUN.keys()), missing
    save(DOC / 'source-row-coverage.json', dict(
        declared_rows=sum(expected.values()), observed_declared_rows=sum(expected.values())-sum(missing.values()),
        gate_sha256=sha(ROOT / 'tests/gate.sh'), binary_sha256=primary['binary_sha256'],
        main_job='jobs/merged-final-uring.json', main_failed_jobs=primary['failed_jobs'],
        missing=[dict(label=name, occurrences=count, status='NOT RUN', reason=NOT_RUN[name])
                 for name, count in missing.items()],
        supplemental_atomic_rows=additions, throwaway_landing_rows=abba_rows,
        differential_aggregate_labels=aggregate_labels, differential_folds=folds,
        private_labels_outside_public_census=list((observed-expected).elements()),
        note='Coverage is execution evidence, not a green verdict. Every original failure is retained. '
             'Partial differential part ledgers are folded into the two declared matrix rows. '
             'Duplicate engine/mode reruns do not increase the public source count.'))
    print('Declared', sum(expected.values()), 'covered', sum(expected.values())-sum(missing.values()),
          'NOT RUN', sum(missing.values()))


if __name__ == '__main__':
    main()
