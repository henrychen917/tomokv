#!/usr/bin/env python3
"""Archive the lane's owned correctness evidence and classify every diagnostic refusal."""
import collections
import gzip
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build/flipfix6'
OUT = ROOT / 'docs/flipfix6'
OUT.mkdir(parents=True, exist_ok=True)


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + '\n')


def classify(directory, label):
    rows = []
    for path in sorted(directory.rglob('server.log')):
        text = path.read_text(errors='replace')
        planned = collections.defaultdict(list)
        failures = []
        for line in text.splitlines():
            if line.startswith('FLIPFIX6 planned '):
                fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                planned[fields['epoch']].append(fields)
            elif line.startswith('FLIPFIX6 failure '):
                fields = {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', line)}
                fields['error'] = line.split(' error=', 1)[1]
                failures.append(fields)
        for failure in failures:
            db1 = '-db1-' in str(path) or '/2s-' in str(path) and '-db1/' in str(path)
            expected_stage = 5 if db1 else 8
            failure['stage_name'] = 'ClientPrepare' if failure['stage'] == expected_stage else 'OTHER'
            failure['planned'] = planned[failure['epoch']]
            failure['clauses'] = []
            for entry in failure['planned']:
                if entry['migration']:
                    continue
                clauses = []
                if not entry['drain']:
                    clauses.append('a flip_drain_idle clause')
                if entry['session']:
                    clauses.append('multi_session_ == nullptr')
                if entry['watched_refs']:
                    clauses.append('watched_refs_ == 0')
                failure['clauses'].append(dict(io=entry['io'], id=entry['id'], clauses=clauses))
            assert failure['stage_name'] == 'ClientPrepare' and failure['deadline'] == 1, failure
            assert any(c['clauses'] for c in failure['clauses']), failure
        all_planned = [entry for group in planned.values() for entry in group]
        row = dict(path=str(path.relative_to(directory)), failures=failures,
                   planned=len(all_planned), sessions=sum(p['session'] for p in all_planned),
                   s2=sum(p['pending'] for p in all_planned),
                   log_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        rows.append(row)
        dest = OUT / label / path.relative_to(directory).with_suffix('.log.gz')
        dest.parent.mkdir(parents=True, exist_ok=True)
        with gzip.GzipFile(filename=str(dest), mode='wb', mtime=0) as stream:
            stream.write(path.read_bytes())
        for name in ('server.argv.json', 'server.exit.json', 'witness.json'):
            source = path.with_name(name)
            if source.exists():
                dest.with_name(name).write_bytes(source.read_bytes())
    result = dict(rows=rows, refusals=sum(len(r['failures']) for r in rows),
                  planned=sum(r['planned'] for r in rows),
                  sessions=sum(r['sessions'] for r in rows), s2=sum(r['s2'] for r in rows))
    save(OUT / f'{label}-diagnosis.json', result)
    return {k: v for k, v in result.items() if k != 'rows'}


summary = {}
for name in ('diagnosis', 'legacy-diagnostic', 'legacy-pre', 'pre-smoke'):
    directory = BUILD / name
    if not (directory / 'results.json').exists():
        continue
    (OUT / f'{name}-results.json').write_bytes((directory / 'results.json').read_bytes())
    if name in ('diagnosis', 'legacy-diagnostic'):
        summary[name] = classify(directory, name)
for name in ('pre-build.log', 'diag-build.log', 'gates-test.log'):
    source = BUILD / name
    if source.exists():
        with gzip.GzipFile(filename=str(OUT / (name + '.gz')), mode='wb', mtime=0) as stream:
            stream.write(source.read_bytes())
save(OUT / 'summary.json', summary)
print(json.dumps(summary, indent=2))
