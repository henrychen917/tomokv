#!/usr/bin/env python3
"""Check complete directed gate legs and retain an oracle/target wire comparison."""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def records(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.startswith('{')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('name')
    args = parser.parse_args()
    receipt = json.loads((ROOT / 'docs/notifycompat' / (args.name + '.json')).read_text())
    base = Path(receipt['artifacts']) / 'jobs'
    positive = receipt['arm'] == 'POST'
    cases = ('setbit', 'setpast', 'emptystore', 'writemiss', 'objectmiss', 'expiredstore', 'flush')
    rows = []
    for case in cases:
        for databases in ((1, 16) if case == 'flush' else (16,)):
            for atomic in (0, 1):
                for mode in ('1s', '2s'):
                    for engine in ('epoll', 'uring'):
                        for read_local in ((0, 1) if mode == '1s' else (0,)):
                            suffix = f'db{databases}-{mode}-{engine}-a{atomic}-rl{read_local}'
                            path = base / 'notifycompat' / f'compat-{case}-{suffix}.log'
                            data = records(path)
                            oracle = [r for r in data if not r['target'] and 'command' in r]
                            target = [r for r in data if r['target'] and 'command' in r]
                            assert oracle and len(oracle) == len(target), (path, 'incomplete scenarios')
                            assert all(a['command'] == b['command'] and a['expected'] == b['expected']
                                       for a, b in zip(oracle, target)), (path, 'different inputs')
                            mismatches = [a['label'] for a, b in zip(oracle, target)
                                          if a['wire_hex'] != b['wire_hex'] or a['reply'] != b['reply']]
                            passed = 'PASS ' + case in path.read_text()
                            assert passed == positive, (path, passed, positive)
                            if not positive:
                                assert mismatches, (path, 'PRE did not reject on wire/reply semantics')
                            else:
                                assert not mismatches, (path, mismatches)
                            rows.append(dict(case=case, leg=suffix, scenarios=len(target),
                                             passed=passed, wire_or_reply_mismatches=mismatches))
    for atomic in (0, 1):
        for mode in ('1s', '2s'):
            for engine in ('epoll', 'uring'):
                for read_local in ((0, 1) if mode == '1s' else (0,)):
                    suffix = f'{mode}-{engine}-a{atomic}-rl{read_local}'
                    path = base / 'tracking_redirect' / f'redirect-{suffix}.log'
                    data = records(path)
                    expected = {(resp, reset, target) for resp in (2, 3)
                                for reset in (False, True) for target in (False, True)}
                    assert {(r['resp'], r['reset'], r['target']) for r in data} == expected, path
                    passed = 'PASS redirect' in path.read_text()
                    assert passed == positive, (path, passed, positive)
                    schedule = base / 'tracking_redirect' / ('schedule-' + suffix)
                    held = list(schedule.rglob('*.held'))
                    replayed = list(schedule.rglob('*.replayed'))
                    assert len(held) >= 4 and len(replayed) >= 4, (path, 'in-flight window not witnessed')
                    rows.append(dict(case='redirect', leg=suffix, scenarios=4, passed=passed,
                                     held_receipts=len(held), replayed_receipts=len(replayed)))
    result = dict(arm=receipt['arm'], sha256=receipt['sha256'], legs=len(rows),
                  scenarios=sum(r['scenarios'] for r in rows), rows=rows)
    output = ROOT / 'docs/notifycompat' / (args.name + '.coverage.json')
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
