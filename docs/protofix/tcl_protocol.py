#!/usr/bin/env python3
"""Protocol-only upstream Tcl diagnostic; never the full performance-bearing job."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
out = ROOT / "build/protofix/tcl-protocol"
out.mkdir(exist_ok=True)
original = ROOT / "tests/redis_tcl_passing.json"
full = json.loads(original.read_text())
selected = {"support": full["support"], "files": {"unit/protocol": full["files"]["unit/protocol"]}}
manifest = out / "protocol-manifest.json"
manifest.write_text(json.dumps(selected, indent=2) + "\n")
rows = []
for mode in ("1s", "2s"):
    command = ["python3", "tests/redis_tcl.py", "--redis-root", "/home/user/Projects/redis",
               "--binary", str(ROOT / "build/tomokv"), "--mode", mode, "--cores", "0-7",
               "--ratio", "6:2", "--port", "20350", "--controller-port", "20351", "--baseport", "20352",
               "--manifest", str(manifest), "--output", str(out / mode)]
    with (out / (mode + ".log")).open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    rows.append(dict(mode=mode, command=command, exit=result.returncode,
                     summary=json.loads((out / mode / "summary.json").read_text())))
receipt = dict(scope="unit/protocol only; full Redis Tcl/compat2 job NOT RUN because it includes SORT speed benchmarks",
               manifest_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
               selected_spec_unchanged=selected["files"]["unit/protocol"] == full["files"]["unit/protocol"],
               binary_sha256=hashlib.sha256((ROOT / "build/tomokv").read_bytes()).hexdigest(), rows=rows)
(ROOT / "docs/protofix/tcl-protocol.json").write_text(json.dumps(receipt, indent=2) + "\n")
assert all(row["exit"] == 0 for row in rows), rows
