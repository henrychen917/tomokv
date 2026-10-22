#!/usr/bin/env python3
"""Use the unmodified differential gate, standard seeds and every declared leg."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
os.sched_setaffinity(0, set(range(89, 96)))
root = Path.cwd()
rows = []
base = root / "docs/moverfix/final-differ"
base.mkdir(parents=True, exist_ok=True)
for engine in ("uring", "epoll"):
    wrapper = root / "build/moverfix" / engine / "tomokv"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text('#!/bin/sh\nexec "' + str(root / "build/tomokv") + '" --net-io ' + engine + ' "$@"\n')
    wrapper.chmod(0o755)
    for geometry in ("split", "armed-fused"):
        directory = base / (engine + "-" + geometry)
        env = dict(os.environ, GATE_LOAD_CORES="89-95", GATE_DIFFER_ORACLE_CORES="88",
                   REDIS74_ROOT="/home/user/Projects/redis74", GATE_DIFFER_GEOMETRY=geometry,
                   GATE_DIFFER_OUT=str(directory), GATE_RUN_ID="moverfix-final-standard",
                   GATE_DIFFER_HISTORY=str(root / ".gate-history/moverfix-differ"))
        cmd = ["tests/differ_gate.sh", str(wrapper), "23820", "23821", "80-87", "6:2"]
        with (base / (engine + "-" + geometry + ".log")).open("w") as f:
            rc = subprocess.run(cmd, env=env, stdout=f, stderr=subprocess.STDOUT).returncode
        row = dict(engine=engine, geometry=geometry, argv=cmd, rc=rc,
                   underlying_binary=str(root / "build/tomokv"),
                   sha256=hashlib.sha256((root / "build/tomokv").read_bytes()).hexdigest(),
                   wrapper_sha256=hashlib.sha256(wrapper.read_bytes()).hexdigest())
        rows.append(row)
        (base / "runs.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(row, flush=True)
