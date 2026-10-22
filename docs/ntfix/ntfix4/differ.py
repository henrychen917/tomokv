#!/usr/bin/env python3
"""Run the unchanged differential coordinator on ntfix's cores and ports."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs/ntfix/ntfix4/differ"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--armed-witness", action="store_true",
                        help="repeat armed INFO with the unchanged string suite's read witness")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "infofix-suites.txt").write_text("infofix\n")
    (OUT / "infofix-seeds.txt").write_text("7\n19\n20\n23\n")
    (OUT / "infofix-witness-suites.txt").write_text("string\ninfofix\n")
    wrappers = {}
    for engine in ("uring", "epoll"):
        path = ROOT / "build/ntfix4" / ("tomokv-" + engine)
        path.write_text('#!/bin/sh\nexec "' + str(ROOT / "build/tomokv") +
                        '" --net-io ' + engine + ' "$@"\n')
        path.chmod(0o755)
        wrappers[engine] = path
    jobs = [("epoll", geometry, True) for geometry in ("split", "armed-fused")]

    if args.armed_witness:
        jobs = [("epoll", "armed-fused", True)]
    rows = []
    for engine, geometry, focused in jobs:
        label = f"{engine}-{geometry}-{'infofix' if focused else 'standard'}"
        if args.armed_witness:
            label += "-witness"
        directory = OUT / label
        env = dict(os.environ,
                   REDIS74_ROOT="/home/user/Projects/redis74",
                   GATE_DIFFER_ORACLE_CORES="88", GATE_LOAD_CORES="89-95",
                   GATE_DIFFER_GEOMETRY=geometry, GATE_DIFFER_OUT=str(directory),
                   GATE_DIFFER_HISTORY=str(ROOT / ".gate-history/differ-ntfix4"),
                   GATE_RUN_ID="ntfix4-infofix")
        if focused:
            suites = "infofix-witness-suites.txt" if geometry == "armed-fused" else "infofix-suites.txt"
            env.update(GATE_DIFFER_PROOF_SUITES=str(OUT / suites),
                       GATE_DIFFER_PROOF_SEEDS=str(OUT / "infofix-seeds.txt"))
        command = ["taskset", "-c", "89-95", "bash", "tests/differ_gate.sh",
                   str(wrappers[engine]), "22810", "22811", "80-87", "6:2"]
        row = dict(label=label, command=command,
                   environment={k: v for k, v in env.items()
                                if k.startswith("GATE_") or k == "REDIS74_ROOT"},
                   binary_sha256=hashlib.sha256((ROOT / "build/tomokv").read_bytes()).hexdigest())
        (OUT / (label + "-command.json")).write_text(json.dumps(row, indent=2) + "\n")
        with (OUT / (label + ".log")).open("w") as log:
            result = subprocess.run(command, env=env, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        row["returncode"] = result.returncode
        rows.append(row)
        results = "witness-results.json" if args.armed_witness else "results.json"
        (OUT / results).write_text(json.dumps(rows, indent=2) + "\n")
        print(f"{label}: rc={result.returncode}", flush=True)
    raise SystemExit(any(r["returncode"] for r in rows))


if __name__ == "__main__":
    main()
