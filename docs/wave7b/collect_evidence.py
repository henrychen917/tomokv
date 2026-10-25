#!/usr/bin/env python3
"""Archive finished wave7b jobs and collect row, suite and fixture wall times."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import tarfile
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/wave7b'
p = argparse.ArgumentParser(); p.add_argument('--final', action='store_true'); args = p.parse_args()
archives = OUT / 'archives'; archives.mkdir(exist_ok=True)

def pack(directory, name):
    dest = archives / (name + '.tar.gz')
    skipped = []
    with dest.open('wb') as raw, gzip.GzipFile(filename='', fileobj=raw, mode='wb', mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode='w') as archive:
            for path in sorted(directory.rglob('*')):
                if path.is_symlink():
                    archive.add(path, arcname=str(path.relative_to(directory)), recursive=False)
                elif path.is_file():
                    with path.open('rb') as stream: magic = stream.read(4)
                    if magic == b'\x7fELF' or path.suffix == '.objdump':
                        skipped.append(str(path.relative_to(directory))); continue
                    archive.add(path, arcname=str(path.relative_to(directory)), recursive=False)
    return dict(path=str(dest.relative_to(ROOT)), sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),
                omitted_generated_binaries_or_disassembly=skipped)

def timings(name):
    directory = ROOT / 'build/wave7b/repetition-timings' / name
    if name == 'abba-smoke': directory = ROOT / 'build/wave7b/smoke-timings'
    dest = OUT / 'timings' / name
    result = {}; fixtures = []
    for path in directory.glob('*.json'):
        dest.mkdir(parents=True, exist_ok=True); shutil.copy2(path, dest / path.name)
        data = json.loads(path.read_text()); stem = Path(data['argv'][0]).stem
        result[stem] = data['seconds']
        if stem == 'gates_test':
            fixtures = [r for r in data['tests'] if 'fixture' in r]
    return result, fixtures

records = []
paths = [ROOT / 'docs/wave7/correctness/wave7b-before/receipt.json',
         *sorted((OUT / 'correctness').glob('*/receipt.json'))]
for path in paths:
    receipt = json.loads(path.read_text())
    if 'exit' not in receipt:
        assert not args.final, ('unfinished job receipt', path)
        continue
    name = path.parent.name
    entry = dict(name=name, receipt=str(path.relative_to(ROOT)), exit=receipt['exit'],
                 wall_seconds=receipt['end']-receipt['start'],
                 binary_sha256=receipt['binary_sha256'],
                 unchanged_binary=receipt['binary_sha256']==receipt['binary_sha256_after'],
                 archive=pack(Path(receipt['run_dir']), name), jobs=receipt['jobs'])
    entry['suite_seconds'], entry['fixtures'] = timings(name)
    records.append(entry)

def scored(row, text):
    return [dict(verdict=v,seconds=float(s),label=label)
            for job in row['jobs'].values() for value in job['rows']
            for v,s,label in [value.split('\t',2)] if text in label]
abba = [dict(name=r['name'],**v) for r in records if r['name']!='wave7b-before'
        for v in scored(r,'ABBA comparison + saturation negative controls')]
flip = [dict(name=r['name'],**v) for r in records if r['name'].startswith('repeat-flip-')
        for v in scored(r,'perfio stale epoll registration (epoll-lb)')]
def stats(rows):
    values=[r['seconds'] for r in rows]
    return dict(count=len(rows),passed=sum(r['verdict']=='ok' for r in rows),
                minimum=min(values),median=statistics.median(values),maximum=max(values)) if values else {}
frozen=[]
for i,row in enumerate(json.loads((OUT/'scheduler-before-timed.json').read_text())):
    frozen.append(dict(options=row['options'], archive=pack(Path(row['artifact']), f'before-scheduler-{i:02}')))
result = dict(records=records,abba_rows=abba,epoll_rows=flip,pre_scheduler_archives=frozen,
              abba_statistics=stats(abba),epoll_statistics=stats(flip))
if args.final:
    assert len(abba)==10 and all(r['verdict']=='ok' for r in abba), abba
    assert len(flip)==10 and all(r['verdict']=='ok' for r in flip), flip
    assert all(r['exit']==0 and r['unchanged_binary'] for r in records if r['name']!='wave7b-before')
(OUT / 'evidence.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k.endswith('statistics')}))
