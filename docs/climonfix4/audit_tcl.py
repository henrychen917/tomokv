#!/usr/bin/env python3
"""Bind the promoted upstream assertions to a completed full-manifest Tcl job."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    run = args.run.resolve()
    assert (run / 'jobs/redis_tcl/done').exists(), 'Tcl job is incomplete'
    wanted = json.loads((ROOT / 'docs/climonfix4/tcl-promotions.json').read_text())
    assert sum(map(len, wanted.values())) == 14
    post = digest(ROOT / 'build/climonfix4/tomokv-POST')
    rows = []
    for mode in ('1s', '2s'):
        folder = run / 'jobs/redis_tcl' / ('redis-tcl-' + mode)
        summary = folder / 'summary.json'
        summary_data = json.loads(summary.read_text())
        assert summary_data['binary_sha256'] == post
        row = dict(mode=mode, binary_sha256=post, artifacts=str(folder),
                   promotions=[], other_named_failures=[], summary_sha256=digest(summary))
        for unit, names in wanted.items():
            result = json.loads((folder / unit / 'result.json').read_text())
            for name in names:
                exact = name + ' in tests/' + unit + '.tcl'
                statuses = [e['status'] for e in result['events'] if e['test'] == exact]
                row['promotions'].append(dict(file=unit, name=name, statuses=statuses))
        for result in summary_data['rows']:
            for event in result.get('events', []):
                if event['status'] == 'err' and event['test'].split(' in tests/')[0]:
                    row['other_named_failures'].append(dict(file=result.get('file'),
                        name=event['test'], data=event['data']))
        row['assertions_passed'] = sum(r['passed'] for r in summary_data['rows'])
        row['manifest_errors'] = [dict(file=r['file'], error=r['error'])
                                  for r in summary_data['rows'] if r['error']]
        row['all_promotions_pass'] = all(p['statuses'] == ['testing', 'ok']
                                         for p in row['promotions'])
        rows.append(row)
    output = ROOT / 'docs/climonfix4/full-tcl-promotions.json'
    output.write_text(json.dumps(rows, indent=2) + '\n')
    for row in rows:
        print(row['mode'], 'promotions:', sum(p['statuses'] == ['testing', 'ok']
              for p in row['promotions']), '/ 14;', 'named failures:',
              len(row['other_named_failures']))
    raise SystemExit(0 if all(r['all_promotions_pass'] for r in rows) else 1)


if __name__ == '__main__':
    main()
