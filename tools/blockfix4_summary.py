#!/usr/bin/env python3
"""Summarize archived gate verdicts and black-box counts without changing verdicts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
RECEIPTS = ROOT / 'docs/blockfix4/gate-receipts'


def totals(rows):
    numbers, maps = Counter(), {}
    for row in rows:
        for key, value in row.items():
            if type(value) is int:
                numbers[key] += value
            elif key in ('mid_llen', 'outcomes'):
                maps.setdefault(key, Counter()).update(value)
    return dict(numbers, **{k: dict(v) for k, v in maps.items()})


def summarize(tag):
    record = json.loads((RECEIPTS / (tag + '.json')).read_text())
    archive = RECEIPTS / (tag + '.tar.gz')
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == record['archive_sha256']
    result = dict(tag=tag, exit_code=record['exit_code'], binary_sha256=record['binary_sha256'],
                  jobs=[{k: j[k] for k in ('job', 'done', 'passed', 'failed', 'rows')}
                        for j in record['jobs']], witnesses={})
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            if not member.name.startswith('jobs/blockfix4/') or not member.name.endswith('/results.json'):
                continue
            case = Path(member.name).parent.name
            rows = json.load(tar.extractfile(member))
            groups = {}
            for server in ('redis', 'tomokv'):
                selected = [r for r in rows if r['label'].startswith(server + '-')]
                group = dict(legs=len(selected), passing=sum(r['passed'] for r in selected),
                             errors={r['label']: r['errors'] for r in selected if not r['passed']})
                summaries = [r['summary'] for r in selected if r['summary']]
                if case == 'scripts':
                    group['script'] = totals([s for s in summaries if 'variant' in s])
                    group['natural_mvcc'] = totals([s for s in summaries if 'order' in s])
                    group['natural_legs'] = [s for s in summaries if 'order' in s]
                elif case in ('creators', 'removed'):
                    names = sorted({name for s in summaries for name in s['results']})
                    group['by_case'] = {name: totals([s['results'][name] for s in summaries
                                                    if name in s['results']]) for name in names}
                    group['totals'] = totals(list(group['by_case'].values()))
                else:
                    group['totals'] = totals(summaries)
                groups[server] = group
            result['witnesses'][case] = groups
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--receipts', nargs='+', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    a.output.write_text(json.dumps([summarize(tag) for tag in a.receipts], indent=2) + '\n')


if __name__ == '__main__':
    main()
