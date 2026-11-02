#!/usr/bin/env python3
"""Losslessly archive large evidence files after their gate job has completed."""
import gzip
import hashlib
import json
import os
from pathlib import Path

assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
receipt = Path('docs/atomfix6/archived-large-evidence.json')
rows = json.loads(receipt.read_text()) if receipt.exists() else []
previous = len(rows)
for run in sorted(Path('build').glob('gate-run.*')):
    jobs = run / 'jobs'
    for job in sorted(jobs.iterdir()) if jobs.exists() else []:
        done = job / 'done'
        if not done.exists():
            continue
        sources = list(job.rglob('server.log'))
        if job.name == 'flipfix6':
            sources += list(job.glob('*/results.json'))
        for source in sorted(sources):
            if source.stat().st_size < 1_000_000:
                continue
            destination = source.with_suffix(source.suffix + '.gz')
            assert not destination.exists()
            data = source.read_bytes()
            compressed = gzip.compress(data, compresslevel=6, mtime=0)
            destination.write_bytes(compressed)
            assert gzip.decompress(destination.read_bytes()) == data
            rows.append(dict(path=str(source), archive=str(destination),
                bytes=len(data), archived_bytes=len(compressed),
                sha256=hashlib.sha256(data).hexdigest(),
                archived_sha256=hashlib.sha256(compressed).hexdigest(),
                job_completion=done.read_text().strip()))
            source.unlink()
receipt.write_text(json.dumps(rows, indent=2) + '\n')
print('Archived evidence:', len(rows) - previous, 'saved bytes:',
      sum(r['bytes'] - r['archived_bytes'] for r in rows[previous:]))
