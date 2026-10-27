#!/usr/bin/env python3
"""Run atomic_floor's two correctness legs without its forbidden rate benchmark.

This is explicitly supplemental, not a passing whole atomic_floor job.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from _gate_process import server

os.sched_setaffinity(0, set(range(8, 16)))
out = ROOT / "docs/protofix/pipeorder"
out.mkdir(exist_ok=True)
binary = ROOT / "build/tomokv"
results = []
for mode in ("1s", "2s"):
    for engine in ("epoll", "uring"):
        directory = out / (mode + "-" + engine)
        args = ["--shards", "16", "--thread-mode", mode, "--net-io", engine,
                "--atomic", "1", "--read-local", "0"]
        if mode == "2s":
            args += ["--ratio", "6:2"]
        try:
            with server(binary, "0-7", 20350, directory, args) as (conn, process):
                assert conn.cmd("DEBUG", "TRIPWIRE", "ARM") == b"OK"
                assert conn.cmd("DEBUG", "TRIPWIRE", "DISARM") == b"OK"
                command = ["python3", "tests/pipeorder.py", "20350", "400"]
                with (directory / "client.log").open("w") as log:
                    result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, timeout=180)
                assert result.returncode == 0, result.returncode
            results.append(dict(mode=mode, engine=engine, passed=True))
        except Exception as error:
            results.append(dict(mode=mode, engine=engine, passed=False, error=repr(error)))
        (out / "receipt.json").write_text(json.dumps(dict(
            binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
            scope="Tripwire round-trip and pipeorder 400 rolls; atomic_floor rate row NOT RUN",
            results=results), indent=2) + "\n")
raise SystemExit(not all(row["passed"] for row in results))
