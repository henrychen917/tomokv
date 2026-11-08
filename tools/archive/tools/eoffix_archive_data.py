#!/usr/bin/env python3
"""Preserve completed correctness-job data before reclaiming build disk space."""
import hashlib
import json
import os
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / 'docs/eoffix'


def main():
    assert os.sched_getaffinity(0) <= set(range(8))
    receipt = DOC / 'archived-data.json'
    records = json.loads(receipt.read_text()) if receipt.exists() else []
    for job in sorted((ROOT / 'build').glob('gate-run.*/jobs/*')):
        if not (job / 'done').exists():
            continue
        paths = [p for p in job.rglob('*.tomo')
                 if p.is_file() and p.stat().st_size >= 16 * 1024 * 1024]
        if not paths:
            continue
        archive = DOC / f'data-{job.parents[1].name}-{job.name}.tar.gz'
        assert not archive.exists(), archive
        entries = []
        with tarfile.open(archive, 'w:gz', compresslevel=1) as tar:
            for path in paths:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                relative = str(path.relative_to(ROOT))
                entries.append(dict(path=relative, bytes=path.stat().st_size, sha256=digest))
                tar.add(path, arcname=relative, recursive=False)
        with tarfile.open(archive, 'r:gz') as tar:
            for entry in entries:
                with tar.extractfile(entry['path']) as stream:
                    assert hashlib.file_digest(stream, 'sha256').hexdigest() == entry['sha256']
        records.append(dict(archive=str(archive.relative_to(ROOT)), files=entries))
        receipt.write_text(json.dumps(records, indent=2) + '\n')
        for path in paths:
            path.unlink()
        print(archive.name, 'preserved bytes', sum(e['bytes'] for e in entries), flush=True)


if __name__ == '__main__':
    main()
