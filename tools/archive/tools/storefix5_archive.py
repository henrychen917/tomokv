#!/usr/bin/env python3
"""Preserve gate receipts and wire transcripts, excluding executables/persistence data."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/storefix5'
assert os.sched_getaffinity(0) <= set(range(16, 24))
directories = set()
for log in DOC.glob('gate-*.log'):
    match = re.search(r'^  artifacts: (.+)$', log.read_text(errors='replace'), re.M)
    if match:
        directory = Path(match[1]).resolve()
        assert directory.is_relative_to(ROOT / 'build')
        directories.add(directory)

paths = []
for directory in sorted(directories):
    for path in sorted(directory.rglob('*')):
        if path.is_file() and not path.is_symlink() and (
                path.name in ('ledger', 'timings', 'done', 'plan.sh') or
                path.name.startswith(('gate-srv-', 'gate-oracle-')) or
                path.suffix in ('.log', '.txt', '.json', '.jsonl', '.tsv', '.csv', '.resp',
                                '.partial', '.err', '.out')):
            paths.append(path)

records = []
destination = DOC / 'gate-receipts.tar.gz'
with destination.open('wb') as output:
    with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0, compresslevel=6) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for path in paths:
                relative = path.relative_to(ROOT)
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                metadata = archive.gettarinfo(str(path), arcname=str(relative))
                metadata.uid = metadata.gid = metadata.mtime = 0
                metadata.uname = metadata.gname = ''
                with path.open('rb') as source:
                    archive.addfile(metadata, source)
                records.append(dict(path=str(relative), bytes=metadata.size, sha256=digest))
manifest = dict(archive=destination.name, bytes=destination.stat().st_size,
                sha256=hashlib.sha256(destination.read_bytes()).hexdigest(), files=records)
(DOC / 'gate-receipts.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(len(records), 'proof artifacts;', destination.stat().st_size, 'compressed bytes')
