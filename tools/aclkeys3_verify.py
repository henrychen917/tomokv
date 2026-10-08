#!/usr/bin/env python3
"""Run directed serverless production-body schedules, never listeners or load."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
KINDS = ('window', 'XREAD', 'XREADGROUP', 'BLMOVE', 'BRPOPLPUSH')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--rounds', type=int, default=6)
    parser.add_argument('--controls', action='store_true')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rows = []
    binaries = {}
    cases = [item for kind in KINDS for item in (kind, kind + '-denied')] + ['window-unblock']

    def run(binary, mode, atomic, case, label, failure=None):
        if str(binary) not in binaries:
            binaries[str(binary)] = hashlib.sha256(binary.read_bytes()).hexdigest()
        command = ['taskset', '-c', '112-119', str(binary), mode, str(atomic), case]
        process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, timeout=10)
        (args.output / (label + '.txt')).write_text(process.stdout)
        passed = ((process.returncode == 0 and 'PASS aclkeys-wake' in process.stdout)
                  if failure is None else
                  (process.returncode == 1 and failure in process.stdout))
        rows.append(dict(label=label, command=command, exit=process.returncode,
                         expected_failure=failure, passed=passed))
        if not passed:
            print('UNEXPECTED', label, process.stdout, flush=True)

    for round_number in range(1, args.rounds + 1):
        first = len(rows)
        for namespace, name in (('db16', 'aclkeys-wake-unit'), ('db0', 'aclkeys-wake-db0-unit')):
            for mode in ('split', 'fused'):
                for atomic in (0, 1):
                    for case in cases:
                        label = f'round-{round_number}-{namespace}-{mode}-a{atomic}-{case}'
                        run(ROOT / 'build' / name, mode, atomic, case, label)
        current = rows[first:]
        print(f'round {round_number}: {sum(row["passed"] for row in current)}/{len(current)}', flush=True)
    if args.controls:
        for control, cases, failure in (
            ('no-wake', ['window'], 'last Task did not renew the consumed IO notification'),
            ('no-acl', ['window-denied', 'XREAD-denied', 'BLMOVE-denied', 'BRPOPLPUSH-denied'],
             'exact admitted/revoked blocking reply'),
            ('no-hold', ['window'], 'owner registration really held')):
            for namespace, name in (('db16', 'aclkeys-wake-unit'), ('db0', 'aclkeys-wake-db0-unit')):
                for mode in ('split', 'fused'):
                    for atomic in (0, 1):
                        for case in cases:
                            run(ROOT / 'build/aclkeys3' / control / name, mode, atomic, case,
                                f'{control}-{namespace}-{mode}-a{atomic}-{case}', failure)
                        if control == 'no-acl':
                            run(ROOT / 'build/aclkeys3' / control / name, mode, atomic,
                                'XREADGROUP-denied', f'{control}-{namespace}-{mode}-a{atomic}-group')
    summary = dict(timestamp=datetime.now(timezone.utc).isoformat(),
                   revision=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                                    text=True).strip(),
                   binaries=binaries, runs=rows, passed=sum(row['passed'] for row in rows),
                   total=len(rows), rounds=args.rounds,
                   limitation='Directed serverless schedules; not loaded gate runs or a measured loss rate.')
    (args.output / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(f'total: {summary["passed"]}/{summary["total"]}', flush=True)
    return int(summary['passed'] != summary['total'])


if __name__ == '__main__':
    raise SystemExit(main())
