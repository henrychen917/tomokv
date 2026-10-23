#!/usr/bin/env python3
"""Keep gate ledgers and complete text witnesses without copying build binaries."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tarfile

os.sched_setaffinity(0, os.sched_getaffinity(0) & set(range(64, 96)))
ROOT = Path(__file__).resolve().parents[2]
for name in sys.argv[1:]:
    dest = ROOT / 'docs/wave5/gate' / name
    receipt = json.loads((dest / 'result.json').read_text())
    manifest, rows = [], []
    archive = dest / 'witnesses.tar.gz'
    with archive.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as tar:
            for run_index, run in enumerate(receipt['run_paths']):
                path = Path(run)
                if not path.is_absolute():
                    path = ROOT / path
                for f in sorted(path.rglob('*')):
                    if not f.is_file() or f.is_symlink():
                        continue
                    rel = str(f.relative_to(path))
                    keep = f.suffix in ('.log', '.txt', '.json', '.tsv', '.csv', '.sh') or f.name in (
                        'ledger', 'timings', 'done', 'output', 'plan')
                    if not keep:
                        continue
                    data = f.read_bytes()
                    manifest.append(dict(run=run_index, file=rel, bytes=len(data),
                                         sha256=hashlib.sha256(data).hexdigest()))
                    tar.add(f, arcname=str(run_index) + '/' + rel, recursive=False)
                    if f.name == 'ledger':
                        for line in data.decode().splitlines():
                            if line.strip():
                                verdict, elapsed, label = line.split('\t', 2)
                                rows.append(dict(job=f.parent.name, verdict=verdict,
                                                 elapsed=elapsed, label=label))
    (dest / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    (dest / 'rows.json').write_text(json.dumps(rows, indent=2) + '\n')
    print(name, len(rows), 'rows;', sum(r['verdict'] != 'ok' for r in rows), 'failures')
