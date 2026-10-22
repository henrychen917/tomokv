#!/usr/bin/env python3
"""Resolve the armed EXEC witness failure without changing its assertions."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path.cwd()
sys.path.insert(0, str(root / "tests"))
from _gate_process import server

os.sched_setaffinity(0, set(range(89, 96)))
# Keep all lane live work and the quiet scheduler test serial.
deadline = time.monotonic() + 7200
while not (root / "docs/moverfix/abba-tail-tailgen_stall.rc").exists():
    assert time.monotonic() < deadline, "preceding correctness work did not finish"
    time.sleep(1)

out = root / "docs/moverfix/atomic-controls"
out.mkdir(parents=True, exist_ok=True)
rows = []
for arm, binary, read_local, databases, cases in [
    ("pre-armed", root / "build/moverfix/pre/tomokv", 1, 16, [("execatomic", [])]),
    ("post-standard", root / "build/tomokv", 0, 1,
     [("atomic_torn", ["--release-build"]),
      ("atomic_ryow", ["--no-rate-assertions"]), ("atomic_hazards", []),
      ("execatomic", [])]),
]:
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    for mode in ("2s", "1s"):
        directory = out / (arm + "-" + mode)
        args = ["--thread-mode", mode, "--atomic", 1, "--databases", databases,
                "--shards", 16, "--read-local", read_local, "--net-io", "uring",
                "--key-lb", 0, "--client-lb", 0, "--flip-auto", 0]
        if mode == "2s":
            args += ["--ratio", "6:2"]
        with server(binary, "80-87", 23810, directory / "server", args):
            for name, flags in cases:
                argv = ["python3", "tests/" + name + ".py", "127.0.0.1", "23810", *flags]
                with (directory / (name + ".log")).open("w") as f:
                    rc = subprocess.run(argv, stdout=f, stderr=subprocess.STDOUT,
                                        timeout=900).returncode
                row = dict(arm=arm, mode=mode, read_local=read_local,
                           databases=databases, sha256=digest, argv=argv, rc=rc)
                rows.append(row)
                (out / "runs.json").write_text(json.dumps(rows, indent=2) + "\n")
                print(row, flush=True)
