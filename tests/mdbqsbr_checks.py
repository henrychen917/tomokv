#!/usr/bin/env python3
"""Run only serverless correctness schedules and require their fault controls to fail."""
import os
from pathlib import Path
import signal
import subprocess
import sys

binary = str(Path(sys.argv[1]).resolve())
env = dict(os.environ, ASAN_OPTIONS="detect_leaks=1", UBSAN_OPTIONS="halt_on_error=1")
outdir = Path(sys.argv[2]) if len(sys.argv) > 2 else None
if outdir:
    outdir.mkdir(parents=True, exist_ok=True)


def run(case, fault, witness, failure=False):
    result = subprocess.run([binary, case, str(fault)], text=True, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
    if outdir:
        (outdir / f"{case}-{fault}.log").write_text(result.stdout)
    if (result.returncode != 0) != bool(fault or failure) or witness not in result.stdout:
        print(result.stdout)
        raise SystemExit(f"FAIL mdbqsbr case={case} fault={fault}: missing expected result/witness")
    if case == "deadline" and (result.returncode != -signal.SIGABRT or
                               "fatal: database retire acknowledgement timeout" not in result.stdout):
        raise SystemExit("FAIL mdbqsbr: deadline did not abort with the production acknowledgement diagnostic")
    print(f"PASS control case={case} fault={fault} exit={result.returncode}: {witness}")


run("all", 0, "PASS mdbqsbr coverage")
for case, fault, witness in [
    ("lifetime", 1, "held map not deleted before final dereference"),
    ("owner", 1, "held map not deleted before final dereference"),
    ("capture", 1, "capture/logical retains map through last dereference"),
    ("logical", 1, "capture/logical retains map through last dereference"),
    ("lifetime", 2, "last-swap maintenance frees held version exactly once"),
    ("entry", 3, "sampled-even participant still owes publication acknowledgement"),
    ("park", 3, "parked/even/role-changing participant not silently exempted"),
    ("role", 3, "parked/even/role-changing participant not silently exempted"),
    ("nested", 4, "held map not deleted before final dereference"),
    ("coverage", 5, "ordinary IO/owner loop covers stamping with read-local off"),
    ("coverage", 3, "role change cannot skip even physical participant"),
    ("backlog", 6, "staggered active readers drain backlog"),
    ("backlog", 2, "staggered active readers drain backlog"),
    ("allocation", 7, "prepared commit performs zero allocations under denial"),
    ("journal", 8, "AOF refusal leaves old mapping live"),
    ("endpoints", 9, "COPY/MOVE endpoints use one immutable version across forced swap"),
    ("wake", 10, "every physical worker has a readable retire doorbell"),
    ("shutdown", 11, "fatal: database retire acknowledgement timeout"),
]:
    run(case, fault, witness)

# A loud production deadline (not the Python subprocess deadline) must identify
# the exact missing participant. A stopped participant follows the positive
# shutdown selection in `all` instead and retains its maps for destruction.
run("deadline", 0, "participant=t1 os_tid=0 ack=0 exited=0", failure=True)
