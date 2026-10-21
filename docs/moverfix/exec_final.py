#!/usr/bin/env python3
"""Bind the unresolved EXEC mover counterexample to the delivered POST binary."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, "tests")
from _gate_process import server

os.sched_setaffinity(0, set(range(89, 96)))
binary = Path("build/tomokv")
digest = hashlib.sha256(binary.read_bytes()).hexdigest()
root = Path("docs/moverfix/exec-final")
root.mkdir(parents=True, exist_ok=True)
rows = []
for mode in ("2s", "1s"):
    directory = root / mode
    args = ["--thread-mode", mode, "--atomic", 0, "--shards", 16,
            "--databases", 16, "--read-local", 0, "--net-io", "uring",
            "--key-lb", 0, "--client-lb", 0, "--flip-auto", 0]
    if mode == "2s":
        args += ["--ratio", "6:2"]
    with server(binary, "80-87", 23810, directory / "server", args) as (_, process):
        assert hashlib.sha256(Path(f"/proc/{process.pid}/exe").read_bytes()).hexdigest() == digest
        argv = ["python3", "tests/moverfix.py", "127.0.0.1", "23810", "--only", "EXEC"]
        with (directory / "test.log").open("w") as f:
            rc = subprocess.run(argv, stdout=f, stderr=subprocess.STDOUT,
                                timeout=180).returncode
        rows.append(dict(mode=mode, sha256=digest, argv=argv, rc=rc))
        (root / "runs.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(rows[-1], flush=True)
