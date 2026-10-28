#!/usr/bin/env python3
"""Retain the gate's individual verdicts and hashes after the live proof ends."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs/exec1s'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    proof = json.loads((DOCS / 'live-proof.json').read_text())
    binary = Path(proof['production_binary'])
    assert sha(binary) == proof['production_sha256']
    runs = []
    for receipt in proof['receipts']:
        log = Path(receipt['log'])
        run = dict(receipt=receipt['receipt'], success=receipt['success'],
                   log=str(log), log_sha256=sha(log), jobs=[])
        if receipt.get('artifacts'):
            root = Path(receipt['artifacts'])
            run['plan_sha256'] = sha(root / 'plan.sh')
            differ_plan = root / 'differ-plan.json'
            if differ_plan.exists():
                run['differ_plan'] = json.loads(differ_plan.read_text())
                run['differ_plan_sha256'] = sha(differ_plan)
            for folder in sorted((root / 'jobs').iterdir()):
                rc, passed, failed = map(int, (folder / 'done').read_text().split())
                ledger = folder / 'ledger'
                rows = []
                for line in ledger.read_text().splitlines():
                    status, seconds, label = line.split('\t', 2)
                    assert status in ('ok', 'FAIL'), (folder, status)
                    rows.append(dict(status=status, seconds=float(seconds), label=label))
                assert passed == sum(row['status'] == 'ok' for row in rows)
                assert failed == sum(row['status'] == 'FAIL' for row in rows)
                run['jobs'].append(dict(name=folder.name, returncode=rc,
                                        passed=passed, failed=failed, rows=rows,
                                        ledger=str(ledger), ledger_sha256=sha(ledger),
                                        output_sha256=sha(folder / 'output.log')))
            selected = set(receipt['selected_jobs'].split())
            observed = {job['name'] for job in run['jobs']}
            assert selected <= observed, selected - observed
            run['selected_jobs'] = sorted(selected)
            run['dependency_jobs'] = sorted(observed - selected)
            run['passed_rows'] = sum(job['passed'] for job in run['jobs'])
            run['failed_rows'] = sum(job['failed'] for job in run['jobs'])
            run['all_jobs_passed'] = all(job['returncode'] == 0 and job['failed'] == 0
                                         for job in run['jobs'])
            assert not receipt['success'] or run['all_jobs_passed']
        runs.append(run)
    record = dict(production_sha256=proof['production_sha256'],
                  proof_sha256=sha(DOCS / 'live-proof.json'),
                  gate_source_sha256=sha(ROOT / 'tests/gate.sh'),
                  runs=runs,
                  all_invocations_passed=all(receipt['success'] for receipt in proof['receipts']),
                  required_coverage_passed=proof.get('required_coverage_passed', proof['passed']),
                  resolved_failures=proof.get('resolved_failures', []),
                  not_run=proof['not_run'])
    (DOCS / 'live-job-results.json').write_text(json.dumps(record, indent=2) + '\n')
    print(len(runs), 'completed invocations;',
          sum(run.get('passed_rows', 0) for run in runs), 'passing rows;',
          sum(run.get('failed_rows', 0) for run in runs), 'failed rows')


if __name__ == '__main__':
    main()
