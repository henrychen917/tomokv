#!/usr/bin/env python3
"""Run only serverless persistence schedules and their clause-deletion controls."""
import json
from pathlib import Path
import subprocess

from shutdown_report import require_persistence

ROOT = Path(__file__).resolve().parents[1]


def main():
    outcomes = []
    schedules = [(ROOT / 'build/persistfix-unit', case, None)
                 for case in ('ack', 'remote', 'shutdown', 'refusal')]
    schedules += [(ROOT / f'build/persistfix-controls/{arm}/unit', case, assertion)
                  for arm, case, assertion in (
                      ('old-ack', 'ack', 'acknowledgement cannot precede post'),
                      ('old-close', 'shutdown', 'writer cannot close before producers stop posting'),
                      ('no-refusal', 'refusal', 'refused post appears in persistence report'))]
    for binary, case, assertion in schedules:
        result = subprocess.run([str(binary), case], cwd=ROOT, text=True,
                                capture_output=True, timeout=15)
        output = result.stdout + result.stderr
        ok = (result.returncode == 1 and f'FAIL persistfix: {assertion}' in output
              if assertion else result.returncode == 0 and 'PASS persistfix' in output)
        if case == 'refusal': ok &= 'AOF refused post: producer=1 recording=0 refused=1' in output
        outcomes.append(dict(binary=str(binary), case=case, expected_failure=assertion,
                             passed=ok, status=result.returncode, output=output))
        print(('PASS' if ok else 'FAIL') + f' {binary.parent.name}/{case}: ' + output.strip())
    clean = dict(enabled=True, recording=False, failed=False, drain_gave_up=False,
                 posted=2, flushed=2, durable=2, refused=0, pending_chunks=0,
                 records_written=2, producers_with_pending=0, producers_stopped=8,
                 producers_expected=8, completions_pending=0)
    require_persistence({'persistence': clean}, enabled=True)
    bad_reports = [{}, {'persistence': dict(clean, refused=1)},
                   {'persistence': dict(clean, pending_chunks=1)},
                   {'persistence': dict(clean, durable=1)},
                   {'persistence': dict(clean, drain_gave_up=True)},
                   {'persistence': dict(clean, producers_stopped=7)}]
    for report in bad_reports:
        try:
            require_persistence(report)
        except SystemExit:
            continue
        raise AssertionError('PS14 checker accepted missing/dirty persistence evidence')
    print('PASS persistfix schema: missing evidence and five dirty shutdowns rejected')
    (ROOT / 'build/persistfix/proofs.json').write_text(json.dumps(outcomes, indent=2) + '\n')
    assert all(item['passed'] for item in outcomes), 'persistence schedule or named negative control failed'


if __name__ == '__main__':
    main()
