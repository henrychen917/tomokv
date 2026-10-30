#!/usr/bin/env python3
"""Index complete gate job receipts without converting partial runs into a gate pass."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/wave11'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collect():
    runs = []
    for receipt in sorted((DOC / 'jobs').glob('*.json')):
        record = json.loads(receipt.read_text())
        if 'artifacts' not in record:
            continue
        directory = Path(record['artifacts'])
        jobs = []
        if not (directory / 'jobs').exists():
            continue
        for job in sorted((directory / 'jobs').iterdir()):
            done = job / 'done'
            row = dict(name=job.name, complete=done.exists(), artifact=str(job))
            if done.exists():
                row['exit'], row['passed'], row['failed'] = map(int, done.read_text().split())
            ledger = job / 'ledger'
            if ledger.exists():
                row['ledger_sha256'] = digest(ledger)
                row['rows'] = [dict(status=parts[0], seconds=parts[1], label=parts[2])
                               for line in ledger.read_text().splitlines()
                               if len(parts := line.split('\t', 2)) == 3]
            jobs.append(row)
        runs.append(dict(name=receipt.stem, receipt=str(receipt.relative_to(ROOT)),
                         receipt_sha256=digest(receipt), binary_sha256=record['binary_sha256'],
                         source_commit=record['source_commit'], gate_sha256=record['gate_sha256'],
                         env=record['env'], exit=record['exit'], seconds=record['seconds'],
                         summary=record.get('summary', []), jobs=jobs))
    return dict(note='Whole GATE_ONLY_JOBS attempts, including failures and superseded attempts. '
                     'Partial invocations are not full-gate receipts. Repeated rows are not new gate declarations.',
                runs=runs)


if __name__ == '__main__':
    result = collect()
    (DOC / 'correctness-jobs.json').write_text(json.dumps(result, indent=2) + '\n')
    for run in result['runs']:
        print(run['name'], run['exit'], '; '.join(run['summary']))
