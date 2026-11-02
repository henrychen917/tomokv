#!/usr/bin/env python3
"""Compress only generated unit debug sections, preserving executable sections."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess

assert set(os.sched_getaffinity(0)) <= set(range(74, 87))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def allocated(path):
    data = path.read_bytes()
    assert data[:6] == b'\x7fELF\x02\x01'
    offset = struct.unpack_from('<Q', data, 40)[0]
    size, count = struct.unpack_from('<HH', data, 58)
    digest = hashlib.sha256()
    for index in range(count):
        _, kind, flags, _, where, length, *_ = struct.unpack_from(
            '<IIQQQQIIQQ', data, offset + index * size)
        if flags & 2:
            digest.update(struct.pack('<IQQ', kind, flags, length))
            if kind != 8:
                digest.update(data[where:where + length])
    return digest.hexdigest()

rows = []
for root in ['build/mdbqsbr-asan', 'build/gate-cache/obj-core-tsan',
             'build/tests', 'build/db0/tests']:
    for path in sorted(Path(root).rglob('*.o')):
        row = dict(path=str(path), before_bytes=path.stat().st_size,
                   before_sha256=sha(path), allocated_sha256=allocated(path),
                   mtime_ns=path.stat().st_mtime_ns)
        subprocess.run(['objcopy', '--preserve-dates', '--compress-debug-sections=zlib',
                        str(path)], check=True)
        assert allocated(path) == row['allocated_sha256']
        assert path.stat().st_mtime_ns == row['mtime_ns']
        row.update(after_bytes=path.stat().st_size, after_sha256=sha(path))
        rows.append(row)
Path('docs/atomfix6/compressed-unit-objects.json').write_text(json.dumps(rows, indent=2) + '\n')
print('unit debug compression:', len(rows), 'objects, saved bytes',
      sum(r['before_bytes'] - r['after_bytes'] for r in rows), flush=True)
