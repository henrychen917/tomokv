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


def ledger_rows(path, partial_selection=None):
    rows = []
    lines = path.read_text().splitlines()
    if partial_selection is not None:
        marker = f'PARTIAL\t0\tGATE_ONLY_JOBS={partial_selection}; NOT A RECEIPT'
        assert lines and lines[0] == marker, (path, lines[:1])
        lines = lines[1:]
    for line in lines:
        status, seconds, label = line.split('\t', 2)
        assert status in ('ok', 'FAIL'), (path, status)
        rows.append(dict(status=status, seconds=float(seconds), label=label))
    return rows


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
                rows = ledger_rows(ledger)
                assert passed == sum(row['status'] == 'ok' for row in rows)
                assert failed == sum(row['status'] == 'FAIL' for row in rows)
                run['jobs'].append(dict(name=folder.name, returncode=rc,
                                        passed=passed, failed=failed, rows=rows,
                                        ledger=str(ledger), ledger_sha256=sha(ledger),
                                        output_sha256=sha(folder / 'output.log')))
                legs = folder / 'differ/legs.tsv'
                if legs.exists():
                    entries = [line.split('\t') for line in legs.read_text().splitlines()]
                    assert all(len(entry) == 6 for entry in entries)
                    failed_legs = []
                    for suite, atomic, seed, repeat, code, filename in entries:
                        if int(code):
                            failed_log = legs.parent / filename
                            failed_legs.append(dict(suite=suite, atomic=int(atomic), seed=int(seed),
                                repeat=int(repeat), returncode=int(code), log=str(failed_log),
                                log_sha256=sha(failed_log)))
                    run['jobs'][-1]['differ_legs'] = dict(path=str(legs), sha256=sha(legs),
                        count=len(entries), failed=failed_legs)
                completion = folder / 'differ/complete.json'
                if completion.exists():
                    run['jobs'][-1]['differ_completion'] = dict(
                        data=json.loads(completion.read_text()), sha256=sha(completion),
                        legs_sha256=sha(folder / 'differ/legs.tsv'))
            selected = set(receipt['selected_jobs'].split())
            observed = {job['name'] for job in run['jobs']}
            # These public groups fold their separately completed children;
            # the gate intentionally creates no job directory for a fold.
            groups = {'differ-split': {'differ-split-0', 'differ-split-1', 'differ-equivalence'},
                      'differ-armed': {'differ-armed-0', 'differ-armed-1'}}
            expanded = set().union(*(groups.get(name, {name}) for name in selected))
            assert expanded <= observed, expanded - observed
            run['selected_jobs'] = sorted(selected)
            run['expanded_selected_jobs'] = sorted(expanded)
            run['dependency_jobs'] = sorted(observed - expanded)
            public_ledger = Path(receipt['receipt']).with_suffix('.ledger.partial')
            run['published_ledger'] = dict(path=str(public_ledger), sha256=sha(public_ledger),
                partial_marker=public_ledger.read_text().splitlines()[0],
                rows=ledger_rows(public_ledger, receipt['selected_jobs']))
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
                  unresolved_failures=proof.get('unresolved_failures', []),
                  not_run=proof['not_run'])
    (DOCS / 'live-job-results.json').write_text(json.dumps(record, indent=2) + '\n')
    print(len(runs), 'completed invocations;',
          sum(run.get('passed_rows', 0) for run in runs), 'passing rows;',
          sum(run.get('failed_rows', 0) for run in runs), 'failed rows')


if __name__ == '__main__':
    main()
