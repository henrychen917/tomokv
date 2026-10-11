"""Focused correctness proof, never a performance measurement."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time

root = Path(__file__).resolve().parents[2]
out = root / "docs/dbdefault"
records = []
for mode in ("split", "armed-fused"):
    env = dict(os.environ, REDIS74_ROOT="/home/user/Projects/redis74",
        GATE_LOAD_CORES="121-127", GATE_DIFFER_ORACLE_CORES="120",
        GATE_DIFFER_PROOF_SUITES=str(out / "differ-suites.txt"),
        GATE_DIFFER_PROOF_SEEDS=str(out / "differ-seeds.txt"),
        GATE_DIFFER_GEOMETRY=mode, GATE_DIFFER_OUT=str(root / "build/dbdefault" / ("differ-" + mode)))
    argv = ["taskset", "-c", "112-127", "tests/differ_gate.sh", str(root / "build/tomokv"),
            "25151", "25152", "112-119", "6:2"]
    start = time.monotonic()
    with (out / ("differ-" + mode + ".log")).open("w") as log:
        rc = subprocess.run(argv, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT).returncode
    records.append(dict(mode=mode, command=argv, environment={k:v for k,v in env.items()
        if k.startswith("GATE_") or k == "REDIS74_ROOT"}, exit_code=rc, seconds=time.monotonic()-start))
    (out / "differ.json").write_text(json.dumps(records, indent=2) + "\n")
    print(mode, rc, flush=True)
