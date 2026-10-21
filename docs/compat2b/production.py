#!/usr/bin/env python3
"""Build the exact job_production_units target inventory; never run a server."""
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/compat2b/production"


def run(command, name):
    with (OUT / f"{name}.log").open("w") as log:
        result = subprocess.run(["taskset", "-c", "64-79", *command], cwd=ROOT,
                                stdout=log, stderr=subprocess.STDOUT)
    row = dict(command=command, returncode=result.returncode)
    print(json.dumps(row), flush=True)
    return row


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    gate = (ROOT / "tests/gate.sh").read_text()
    body = gate.split("job_production_units(){", 1)[1].split("\n}", 1)[0]
    targets = sorted(set(re.findall(r"build/[A-Za-z0-9_.-]+", body)))
    (OUT / "targets.txt").write_text("\n".join(targets + ["mdbqsbr-live-arms"]) + "\n")
    receipts = [run(["make", "-k", "-j16", "all", *targets], "build")]
    for target in ["all", *targets]:
        receipts.append(run(["make", "-q", target], "fresh-" + target.replace("/", "_")))
    receipts.append(run(["make", "-j16", "mdbqsbr-live-arms"], "mdbqsbr-live-arms-build"))
    # The parent target is intentionally phony. Check each concrete arm through
    # its original BUILD_ROOT and flags, not `make -q` on the phony coordinator.
    for arm, extra in (("park", ""), ("no-wake", " -DTOMO_MDBQSBR_NO_WAKE")):
        receipts.append(run(
            ["make", "-q", "BUILD_ROOT=build/mdbqsbr2-" + arm,
             "CXXFLAGS=-std=c++20 -O2 -g -Wall -Wextra -march=native -pthread"
             " -DTOMO_MDBQSBR_LIVE_PARK" + extra, "all"], "fresh-mdbqsbr2-" + arm))
    (OUT / "results.json").write_text(json.dumps(receipts, indent=2) + "\n")
    raise SystemExit(any(r["returncode"] for r in receipts))


if __name__ == "__main__":
    main()
