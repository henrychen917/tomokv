#!/usr/bin/env python3
"""Retain complete text receipts for every lane attempt, including failures."""
import hashlib
import json
import os
from pathlib import Path
import stat
import tarfile

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
DOC = ROOT / "docs/protofix"
runs = {ROOT / "build" / name for name in
        ("gate-run.EmQy06", "gate-run.RjoURp", "gate-run.Usxxod")}
for path in (DOC / "jobs").glob("*.json"):
    receipt = json.loads(path.read_text())
    if receipt.get("artifacts"):
        runs.add(Path(receipt["artifacts"]))
files = set()
for folder in runs:
    assert folder.is_dir(), folder
    files.update(path for path in folder.rglob("*") if not path.is_dir())
files.update((ROOT / "build/protofix").glob("*.log"))
rows = []
with tarfile.open(DOC / "runtime-evidence.tar.gz", "w:gz") as archive:
    for path in sorted(files):
        relative = str(path.relative_to(ROOT))
        if not stat.S_ISREG(path.lstat().st_mode):
            rows.append(dict(path=relative, retained=False, reason="nonregular generated artifact"))
            continue
        with path.open("rb") as stream:
            prefix = stream.read(32)
            stream.seek(0)
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        size = path.stat().st_size
        reason = None
        if prefix.startswith(b"\x7fELF") or path.suffix in (".o", ".a", ".so"):
            reason = "generated executable/object; hash retained, artifact stays in build/"
        elif path.suffix in (".pem", ".key", ".crt", ".rdb", ".aof"):
            reason = "regenerable test certificate or persistence data"
        elif size > 4 * 1024 * 1024 and path.suffix not in (".log", ".txt", ".json", ".tsv"):
            reason = "large generated test payload"
        if reason is None:
            archive.add(path, arcname=relative, recursive=False)
        rows.append(dict(path=relative, bytes=size, sha256=digest, retained=reason is None,
                         **({"reason": reason} if reason else {})))
(DOC / "runtime-evidence.json").write_text(json.dumps(dict(
    runs=sorted(str(path.relative_to(ROOT)) for path in runs), files=rows,
    archive_sha256=hashlib.sha256((DOC / "runtime-evidence.tar.gz").read_bytes()).hexdigest()), indent=2) + "\n")
print("retained", sum(row["retained"] for row in rows), "files from", len(runs), "gate invocations")
