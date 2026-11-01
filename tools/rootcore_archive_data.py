#!/usr/bin/env python3
"""Archive generated persistence data only after its completed proof is retained."""
import hashlib
import json
import os
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
assert os.sched_getaffinity(0) <= set(range(16, 32))
receipts = root / 'docs/rootcore/data-archives.json'
records = json.loads(receipts.read_text()) if receipts.exists() else []
completed = {row['phase'] for row in records}
destination = root / 'build/rootcore/data-archives'
destination.mkdir(parents=True, exist_ok=True)
for path in sorted((root / 'docs/rootcore/proof').glob('*.json')):
    meta = json.loads(path.read_text())
    if not isinstance(meta, dict) or 'run_directory' not in meta:
        continue
    name = meta['name']
    if name in completed:
        continue
    assert not meta['missing_jobs'], path
    assert all(job['done'] is not None for job in meta['jobs'].values()), path
    logs = path.with_suffix('.tar.gz')
    with logs.open('rb') as source:
        assert hashlib.file_digest(source, 'sha256').hexdigest() == meta['archive_sha256']
    run = Path(meta['run_directory']).resolve()
    run.relative_to(root / 'build')
    assert run.name.startswith('gate-run.'), run
    files = [file for file in sorted(run.rglob('*')) if file.is_file()
             and not file.is_symlink() and file.suffix in ('.tomo', '.aof', '.rdb')]
    if not files:
        continue
    members = [str(file.relative_to(run)) for file in files]
    before = sum(file.stat().st_size for file in files)
    archive = destination / (name + '.tar.gz')
    assert not archive.exists(), archive
    with tarfile.open(archive, 'w:gz', compresslevel=1) as output:
        for file, member in zip(files, members):
            output.add(file, arcname=member, recursive=False)
    with archive.open('rb') as source:
        os.fsync(source.fileno())
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    # Verify every member and decompressed byte before removing a loose copy.
    with tarfile.open(archive, 'r:gz') as saved:
        assert saved.getnames() == members
        for file, member in zip(files, members):
            with file.open('rb') as original, saved.extractfile(member) as copy:
                assert hashlib.file_digest(original, 'sha256').digest() == \
                       hashlib.file_digest(copy, 'sha256').digest(), file
    record = dict(phase=name, run_directory=str(run), archive=str(archive.relative_to(root)),
                  sha256=digest, original_bytes=before, archive_bytes=archive.stat().st_size,
                  members=members)
    records.append(record)
    receipts.write_text(json.dumps(records, indent=2) + '\n')
    for file in files:
        file.unlink()
    print(json.dumps({k: v for k, v in record.items() if k != 'members'}), flush=True)
