#!/usr/bin/env python3
"""Unchanged atomic/transaction batteries and armed mover coverage."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from _gate_process import server
os.sched_setaffinity(0, set(range(89, 96)))
root = Path("docs/moverfix/final-supplement")
root.mkdir(parents=True, exist_ok=True)
rows = []
binary = Path("build/tomokv")
digest = hashlib.sha256(binary.read_bytes()).hexdigest()

def run(directory, mode, atomic, engine, dbs, tests):
    args = ["--thread-mode", mode, "--atomic", atomic, "--shards", 16,
            "--databases", dbs, "--read-local", 1, "--net-io", engine,
            "--key-lb", 0, "--client-lb", 0, "--flip-auto", 0]
    if mode == "2s":
        args += ["--ratio", "6:2"]
    with server(binary, "80-87", 23810, directory / "server", args):
        for name, flags in tests:
            cmd = ["python3", "tests/" + name + ".py", "127.0.0.1", "23810", *flags]
            with (directory / (name + ".log")).open("w") as f:
                result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=900)
            row = dict(mode=mode, atomic=atomic, engine=engine, databases=dbs,
                       argv=cmd, sha256=digest, rc=result.returncode)
            rows.append(row)
            (root / "runs.json").write_text(json.dumps(rows, indent=2) + "\n")
            print(row, flush=True)
for mode in ("2s", "1s"):
    run(root / (mode + "-atomic1"), mode, 1, "uring", 16,
        [("atomic_torn", ["--release-build"]),
         ("atomic_ryow", ["--no-rate-assertions"]), ("atomic_hazards", []),
         *[(name, []) for name in ("multi_exec", "atomfix", "scriptatomic", "execatomic", "execiso", "execfix", "multires", "multirace", "session_monotonic", "xacct")],
         ("xmove", ["--release-build"]), ("xscript", [])])
for mode in ("2s", "1s"):
    for engine in ("uring", "epoll"):
        for dbs in (1, 16):
            run(root / f"armed-{mode}-{engine}-db{dbs}", mode, 0, engine, dbs, [("txn_movers", [])])
