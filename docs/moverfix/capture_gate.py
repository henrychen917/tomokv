#!/usr/bin/env python3
"""Retain the gate's own row receipts, completion files and build/test logs."""
import gzip
import hashlib
import json
from pathlib import Path
import sys
src, dst = map(Path, sys.argv[1:3])
assert src.is_dir() and not dst.exists()
dst.mkdir(parents=True)
files=[]
for path in sorted(src.rglob("*")):
    if not path.is_file() or path.is_symlink():
        continue
    if path.name not in ("done", "ledger", "row-context", "plan.sh", "phases.tsv", "slot", "live-pids") and path.suffix not in (".log", ".txt", ".json", ".tsv", ".partial", ".timings"):
        continue
    # Data files and copied compiler/test source trees are not run evidence.
    if any("gate-data-" in part for part in path.relative_to(src).parts):
        continue
    payload = path.read_bytes()
    rel = path.relative_to(src)
    target=dst/rel
    target.parent.mkdir(parents=True,exist_ok=True)
    if len(payload)>65536:
        target=target.with_name(target.name+".gz")
        target.write_bytes(gzip.compress(payload,mtime=0))
    else:
        target.write_bytes(payload)
    files.append(dict(source=str(path),saved=str(target.relative_to(dst)),
                      bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest()))
(dst/"manifest.json").write_text(json.dumps(files,indent=2)+"\n")
print("saved",len(files),"files")
