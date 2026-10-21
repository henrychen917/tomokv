#!/usr/bin/env python3
"""Repeat the unchanged failing expiry suite on PRE and POST, with full receipts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/ntfix/ntfix2/expiry"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--pre-only", action="store_true")
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "suites.txt").write_text("hexpire\n")
    (out / "seeds.txt").write_text("7\n19\n20\n23\n")
    rows = []
    arms = [("pre", "build/ntfix-pre/tomokv")]
    if not args.pre_only:
        arms.append(("post", "build/tomokv"))
    jobs = [(arm, relative, repeat) for arm, relative in arms
            for repeat in range(1, args.repeats + 1)]
    for arm, relative, repeat in jobs:
        label = arm if args.repeats == 1 else f"{arm}-r{repeat}"
        binary = ROOT / relative
        wrapper = ROOT / "build/ntfix2" / (arm + "-expiry-uring")
        wrapper.write_text("#!/bin/sh\nexec " + shlex.quote(str(binary)) +
                           ' --net-io uring "$@"\n')
        wrapper.chmod(0o755)
        env = dict(os.environ, REDIS74_ROOT="/home/user/Projects/redis74",
                   GATE_DIFFER_ORACLE_CORES="104", GATE_LOAD_CORES="105-111",
                   GATE_DIFFER_GEOMETRY="split", GATE_DIFFER_OUT=str(out / label),
                   GATE_DIFFER_HISTORY=str(ROOT / ".gate-history/differ-ntfix2-expiry"),
                   GATE_RUN_ID="ntfix2-expiry",
                   GATE_DIFFER_PROOF_SUITES=str(out / "suites.txt"),
                   GATE_DIFFER_PROOF_SEEDS=str(out / "seeds.txt"))
        command = ["taskset", "-c", "105-111", "bash", "tests/differ_gate.sh",
                   str(wrapper), "25810", "25811", "96-103", "6:2"]
        row = dict(arm=arm, repeat=repeat, command=command,
                   binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                   environment={k: v for k, v in env.items()
                                if k.startswith("GATE_") or k == "REDIS74_ROOT"})
        with (out / (label + ".log")).open("w") as log:
            result = subprocess.run(command, env=env, cwd=ROOT, stdout=log,
                                    stderr=subprocess.STDOUT)
        row["returncode"] = result.returncode
        rows.append(row)
        (out / "results.json").write_text(json.dumps(rows, indent=2) + "\n")
        print(f"{label} unchanged hexpire: rc={result.returncode}", flush=True)
    # A baseline failure is diagnostic evidence, not a passing test or a waiver.


if __name__ == "__main__":
    main()
