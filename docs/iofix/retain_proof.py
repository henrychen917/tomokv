#!/usr/bin/env python3
"""Retain gate-owned logs/receipts, excluding executables and persistence data."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('run', type=Path)
p.add_argument('destination', type=Path)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--note', required=True)
a = p.parse_args()
kept = []
for source in sorted(a.run.rglob('*')):
    if not source.is_file() or source.is_symlink():
        continue
    rel = source.relative_to(a.run)
    if source.name in ('ledger', 'ledger.partial', 'ledger.partial.timings', 'timings', 'plan.sh') or source.suffix in ('.log', '.txt', '.json', '.jsonl', '.tsv', '.conf'):
        dest = a.destination / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, dest)
        kept.append(dict(path=str(rel), bytes=source.stat().st_size,
                         sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
a.destination.mkdir(parents=True, exist_ok=True)
manifest = dict(run=str(a.run.resolve()), binary=str(a.binary.resolve()),
                binary_sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest(),
                note=a.note, files=kept)
(a.destination / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(dict(destination=str(a.destination), files=len(kept),
                      bytes=sum(x['bytes'] for x in kept))))
