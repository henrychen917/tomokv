#!/usr/bin/env python3
"""Compact completed diagnostic evidence; never operate on a running gate job."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import tarfile

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
DOC = Path(__file__).resolve().parent
old = sorted(DOC.glob('instructions-fast-*')) + [
    DOC / name for name in ('instructions', 'identity-initial', 'identity-executor',
                            'identity-final', 'callsites', 'callsites-final',
                            'budgets-final')]
old = [p for p in old if p.is_dir()]
if old:
    archive = DOC.parents[1] / 'build/wave5/diagnostic-trials.tar.gz'
    assert not archive.exists(), 'Do not overwrite a previous diagnostic archive'
    manifest = []
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for directory in old:
                for path in sorted(directory.rglob('*')):
                    if not path.is_file():
                        continue
                    data = path.read_bytes()
                    name = str(path.relative_to(DOC))
                    manifest.append(dict(path=name, bytes=len(data),
                                         sha256=hashlib.sha256(data).hexdigest()))
                    tar.add(path, arcname=name, recursive=False)
    (DOC / 'diagnostic-trials-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    for directory in old:
        shutil.rmtree(directory)
    print('Archived', len(manifest), 'diagnostic files:', archive.stat().st_size, 'bytes')

for directory in ('instructions-landing', 'callsites-landing', 'callsites-scatter'):
    root = DOC / directory
    for path in sorted(root.glob('*.log')) + sorted(root.glob('diff-*.txt')):
        compressed = path.with_name(path.name + '.gz')
        with compressed.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as target:
            target.write(path.read_bytes())
        path.unlink()
    summary = root / 'summary.json'
    if summary.exists():
        rows = json.loads(summary.read_text())
        for row in rows:
            if 'diff' in row and not row['diff'].endswith('.gz'):
                row['diff'] += '.gz'
        summary.write_text(json.dumps(rows, indent=2) + '\n')
