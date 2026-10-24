#!/usr/bin/env python3
"""Index retained gate receipts without substituting for their acceptance jobs."""
import collections
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / 'docs/notifycompat'
ARMS = {
    'PRE': 'a1953bcbd75e9dd5f468ea2340c5f26fb855864148cd5efd1fac806751bff54e',
    'POST': '76f313519a120bf5b65efe74338ce0ba142dc5a4f441590fc1e995c61b308b59',
    'PAD-A': '638ecff86821cb4d84916382ae0f6baac9fe78e4b41e1fa660130196e81b94af',
}


def main():
    selected = json.loads((EVIDENCE / 'proof-selection.json').read_text())
    missing, runs, failures = [], [], []
    totals = collections.defaultdict(collections.Counter)
    for selection in selected:
        name = selection['receipt']
        path = EVIDENCE / (name + '.json')
        if not path.exists():
            missing.append(name)
            continue
        receipt = json.loads(path.read_text())
        arm = receipt['arm']
        assert receipt['sha256'] == ARMS[arm], (name, 'wrong merit arm')
        assert receipt['environment']['GATE_ONLY_JOBS'].split() == receipt['jobs']
        jobs = selection.get('jobs', receipt['jobs'])
        assert set(jobs) <= set(receipt['jobs']), (name, 'job was not selected')
        archive_path = EVIDENCE / (name + '.evidence.tar.gz')
        result = dict(receipt=name, arm=arm, gate_exit=receipt['exit'],
                      sha256=receipt['sha256'], engine=receipt['engine'],
                      fused=receipt['fused'], jobs=[])
        with tarfile.open(archive_path) as archive:
            for job in jobs:
                prefix = 'jobs/' + job + '/'
                ledger = archive.extractfile(prefix + 'ledger').read().decode()
                family = archive.extractfile(prefix + 'family.tsv').read().decode().strip()
                assert family.split('\t')[0] == job, (name, job, 'missing completed family')
                rows = []
                for line in ledger.splitlines():
                    status, duration, label = line.split('\t', 2)
                    assert status in ('ok', 'FAIL'), (name, line)
                    rows.append(dict(status=status, seconds=float(duration), label=label))
                    totals[arm][status] += 1
                    if status == 'FAIL':
                        failures.append(dict(receipt=name, arm=arm, job=job, label=label))
                assert rows, (name, job, 'requested job emitted no scored row')
                result['jobs'].append(dict(name=job, family=family, rows=rows))
        result['evidence_sha256'] = hashlib.file_digest(archive_path.open('rb'), 'sha256').hexdigest()
        runs.append(result)
    output = dict(missing=missing, totals=dict(totals), failures=failures, runs=runs)
    (EVIDENCE / 'proof-index.json').write_text(json.dumps(output, indent=2) + '\n')
    print(json.dumps(dict(missing=missing, totals=dict(totals), failures=failures), indent=2))
    # PRE/PAD failures are retained for explicit review, not automatically accepted.
    assert not missing, 'required receipt(s) still pending'
    assert not any(f['arm'] == 'POST' for f in failures), 'POST has a failed selected whole job'


if __name__ == '__main__':
    main()
