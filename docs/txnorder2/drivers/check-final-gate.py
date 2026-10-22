#!/usr/bin/env python3
"""Check completion and every declared leg of the selected final gate run.

This reads the gate's own evidence. It does not manufacture gate rows or turn
negative controls into positive results. The separate source-count refusal
and PRE wake job remain separate receipts.
"""
import hashlib
import itertools
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / 'docs/txnorder2'


def main():
    run = DOCS / 'gate-final2d'
    result = json.loads((run / 'result.json').read_text())
    assert result['status'] == 'PASS' and result['stable_binary'], result
    scope = json.loads((DOCS / 'resume/scope.json').read_text())
    assert set(scope['gate_jobs']) <= result['jobs'].keys()
    jobs = {k: list(map(int, v.split())) for k, v in result['jobs'].items()}
    assert all(code == 0 and failed == 0 for code, passed, failed in jobs.values())
    assert jobs['txnorder2'] == [0, 16, 0]
    assert jobs['txnorder_wake'] == [0, 1, 0]
    target = run / 'run/jobs/txnorder2'
    checked = []

    def read(path):
        data = path.read_bytes()
        checked.append(dict(path=str(path.relative_to(DOCS)), bytes=len(data),
                            sha256=hashlib.sha256(data).hexdigest()))
        return data.decode().splitlines()

    for index in range(1, 13):
        lines = read(target / f'R{index}.log')
        assert f'PASS R{index}' in lines
        if index == 8:
            assert lines.count('PASS WATCH owner-turn regression') == 4
        if index == 12:
            assert all('PASS ' + case in lines for case in ('invariant', 'failure', 'retirement'))
            for shape, states in enumerate((14, 7, 11, 11, 4, 4, 4), 1):
                expected = f'R{shape} exhaustive: {states} owner states, {states * 5} transitions, fair cycle=0'
                assert expected in lines
    assert read(target / 'rename.log').count('PASS WATCH owner-turn regression') == 2
    for family, mode, engine, databases in itertools.product(
            ('serve', 'flush', 'readonly'), ('1s', '2s'), ('uring', 'epoll'), (1, 16)):
        lines = read(target / f'{family}-{mode}-{engine}-{databases}.log')
        passes = [line for line in lines if line.startswith('PASS ')]
        if family == 'serve':
            assert len(passes) == 19 and passes[6] == 'PASS WATCH owner-turn regression'
            for command in ('BLPOP', 'BRPOP', 'BLMPOP', 'BZPOPMIN', 'BZPOPMAX', 'BZMPOP'):
                assert f'PASS served {command}: WATCH saw one, serve removed it and dirtied WATCH' in passes
            assert 'PASS EXEC XADD then XREADGROUP dirties WATCH None' in passes
        elif family == 'flush':
            assert len(passes) == (16 if databases == 1 else 24)
            assert 'PASS FLUSHALL key expires after WATCH None' in passes
        else:
            assert passes == ['PASS WATCH owner-turn regression', 'PASS W1', 'PASS W2', 'PASS S5']
    wake = read(run / 'run/jobs/txnorder_wake/wake.log')
    for mode in ('1s', '2s'):
        assert f'PASS {mode} busy owner recovered a queued task without an idle turn' in wake
    summary = dict(status='PASS', binary_sha256=result['sha256'],
                   requested_jobs=len(scope['gate_jobs']), completed_jobs=len(jobs),
                   job_scored_passes=sum(v[1] for v in jobs.values()),
                   job_scored_failures=sum(v[2] for v in jobs.values()),
                   ledger_verdicts=result['ledger_verdicts'],
                   new_rows=17, watch_mode_engine_database_legs=24,
                   handshake_legs=4, rename_namespace_legs=2, wake_modes=2,
                   checked_receipts=checked,
                   note='Selected correctness jobs only. Each differential part aggregates its '
                        'internal comparisons into one scored row. No full iteration/source/'
                        'performance receipt claimed.')
    (DOCS / 'resume/final-gate-coverage.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'checked_receipts'}, indent=2))


if __name__ == '__main__':
    main()
