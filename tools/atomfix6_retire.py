#!/usr/bin/env python3
"""Retire large payloads only after their correctness job has passed."""
import hashlib
import json
import os
from pathlib import Path

assert set(os.sched_getaffinity(0)) <= set(range(74, 87))
root = Path.cwd()
receipt = Path('docs/atomfix6/retired-persistence-data.json')
rows = json.loads(receipt.read_text()) if receipt.exists() else []
old_count = len(rows)
for run in sorted(Path('build').glob('gate-run.*')):
    jobs = run / 'jobs'
    for job in sorted(jobs.iterdir()) if jobs.exists() else []:
        done = job / 'done'
        if not done.exists(): continue
        fields = done.read_text().split()
        if len(fields) != 3 or fields[0] != '0' or fields[2] != '0': continue
        for path in sorted(job.rglob('*')):
            if not path.is_file() or path.stat().st_size < 1_000_000: continue
            if path.suffix not in ('.tomo', '.rdb', '.cut', '.aof'): continue
            assert path.resolve().is_relative_to(root / 'build')
            data = path.read_bytes()
            assert data[:4] != b'\x7fELF'
            rows.append(dict(path=str(path), bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                job_completion=done.read_text().strip()))
            path.unlink()
receipt.write_text(json.dumps(rows, indent=2) + '\n')
print('Retired completed-test payloads:', len(rows) - old_count, 'files,',
      sum(r['bytes'] for r in rows[old_count:]), 'bytes', flush=True)
