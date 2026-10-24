#!/usr/bin/env python3
"""Replay interrupted Climon legs through differ_gate.sh's focused-proof interface."""
import json
import os
from pathlib import Path
import subprocess
import sys

arm, engine, port, cores, load = sys.argv[1:]
root = Path(__file__).resolve().parents[1]
out = root / "docs/blockfix"
proof = root / "build/blockfix/climon"
proof.mkdir(exist_ok=True)
seeds = out / "climon-seeds.txt"
suites = out / "climon-suites.txt"
binary = root / ("build/tomokv" if arm == "POST" else "build/blockfix/PRE/tomokv")
results = []
for geometry in ("split", "armed-fused"):
    name = f"climon-{arm.lower()}-{engine}-{geometry}"
    directory = proof / name
    env = dict(os.environ, GATE_DIFFER_GEOMETRY=geometry, GATE_DIFFER_NET_IO=engine,
               GATE_LOAD_CORES=load, GATE_DIFFER_OUT=str(directory),
               GATE_DIFFER_PROOF_SEEDS=str(seeds), GATE_DIFFER_PROOF_SUITES=str(suites),
               REDIS74_ROOT="/home/user/Projects/redis",
               GATE_DIFFER_ORACLE_BIN="/home/user/Projects/redis74/src/redis-server",
               GATE_DIFFER_REDIS_CLI="/home/user/Projects/redis74/src/redis-cli")
    command = ["tests/differ_gate.sh", str(binary), port, str(int(port)+1), cores, "6:2"]
    with (out / (name + ".log")).open("w") as log:
        result = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    results.append(dict(geometry=geometry, command=command, directory=str(directory), rc=result.returncode))
    print(name, result.returncode, flush=True)
(out / f"climon-{arm.lower()}-{engine}.json").write_text(json.dumps(results, indent=2) + "\n")
raise SystemExit(any(r["rc"] for r in results))
