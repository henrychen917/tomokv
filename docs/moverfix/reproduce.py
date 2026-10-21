#!/usr/bin/env python3
"""Original D2 controls; servers and clients use the lane allocation only."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from _gate_process import server

p = argparse.ArgumentParser()
p.add_argument("binary", type=Path)
p.add_argument("output", type=Path)
p.add_argument("--full", action="store_true")
a = p.parse_args()
os.sched_setaffinity(0, set(range(89, 96)))
a.output.mkdir(parents=True, exist_ok=True)
rows = json.loads((a.output / "runs.json").read_text()) if (a.output / "runs.json").exists() else []
for mode in ("2s", "1s"):
    for dbs in (1, 16):
        for engine in ("uring", "epoll"):
            d = a.output / f"{mode}-db{dbs}-{engine}"
            if any(r["mode"] == mode and r["databases"] == dbs and r["engine"] == engine for r in rows):
                continue
            argv = ["--thread-mode", mode, "--atomic", 0, "--shards", 16,
                    "--databases", dbs, "--net-io", engine,
                    "--read-local", 0, "--key-lb", 0, "--client-lb", 0, "--flip-auto", 0]
            if mode == "2s":
                argv += ["--ratio", "6:2"]
            with server(a.binary, "80-87", 23800, d / "server", argv):
                cases = [("T05", ["tests/moverfix.py", "--only", "T05"]),
                         ("G5", ["tests/moverfix.py", "--only", "G5"])]
                if a.full:
                    cases += [("families", ["tests/txn_movers.py"])]
                for name, test in cases:
                    cmd = ["taskset", "-c", "89-95", "python3", test[0], "127.0.0.1", "23800", *test[1:]]
                    with (d / (name + ".log")).open("w") as f:
                        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, timeout=180)
                    row = dict(mode=mode, databases=dbs, engine=engine, case=name,
                               argv=cmd, rc=result.returncode,
                               sha256=hashlib.sha256(a.binary.read_bytes()).hexdigest())
                    rows.append(row)
                    (a.output / "runs.json").write_text(json.dumps(rows, indent=2) + "\n")
                    print(mode, dbs, engine, name, result.returncode, flush=True)
