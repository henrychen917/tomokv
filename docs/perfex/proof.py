#!/usr/bin/env python3
"""Focused proof stages; does not invoke gate.sh or a mainline benchmark."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/perfex"
RESULTS = []
sys.path.insert(0, str(ROOT / "tests"))
from perfex_checks import server


def run(argv, label, env=None):
    argv = ["taskset", "-c", "112-127", *map(str, argv)]
    print("RUN " + label, flush=True)
    path = OUT / (label + ".log")
    before = time.monotonic()
    with path.open("w") as stream:
        result = subprocess.run(argv, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                                env=dict(os.environ, **(env or {})))
    row = dict(command=argv, environment=env or {}, exit_code=result.returncode,
               seconds=time.monotonic() - before, log=str(path.relative_to(ROOT)))
    with (OUT / "commands.jsonl").open("a") as stream:
        stream.write(json.dumps(row) + "\n")
    RESULTS.append(row)
    print(f"DONE {label}: {result.returncode}", flush=True)
    return row


def units():
    gate = (ROOT / "tests/gate.sh").read_text()
    body = gate.split("job_production_units(){", 1)[1].split("job_multidb(){", 1)[0]
    command = body.split("make -k", 1)[1].split('>"$TMPDIR/build.log"', 1)[0]
    targets = re.findall(r"\bbuild/[\w-]+", command)
    assert len(targets) == len(set(targets)) == 28, targets
    row = run(["make", "-k", "-j16", *targets], "production-units-build")
    freshness = []
    for target in targets:
        status = subprocess.run(["taskset", "-c", "112-127", "make", "-q", target], cwd=ROOT).returncode
        freshness.append(dict(target=target, exit_code=status))
    RESULTS.extend(freshness)
    arms = run(["make", "-j16", "mdbqsbr-live-arms"], "mdbqsbr-live-arms-build")
    (OUT / "production-units.json").write_text(json.dumps(
        dict(build=row, freshness=freshness, live_arms=arms), indent=2) + "\n")
    run(["python3", "tests/storesize_checks.py", "check-all", "build/storesize-unit"], "storesize-unit")
    for group in ("publication", "watch", "metadata"):
        run(["python3", "tests/exbatch_checks.py", group], "exbatch-" + group)
    run(["python3", "tests/wbland_checks.py", "check", "clauses"], "wbland-clauses")


def correctness():
    for check in ("clock", "batch"):
        run(["python3", "tests/perfex_checks.py", check, "--binary", "build/tomokv"], "post-" + check)
    for mode in ("2s", "1s"):
        run(["taskset", "-c", "120-127", "python3", "tests/perfex_checks.py", "sampler",
             "--binary", "build/tomokv", "--port", "25100", "--cores", "112-119", "--mode", mode],
            "post-sampler-" + mode)
        with server(ROOT / "build/tomokv", 25102, "112-119", mode):
            run(["taskset", "-c", "120-127", "python3", "tests/infofix.py", "127.0.0.1", "25102"],
                "infofix-" + mode)
    (OUT / "differ-suites.txt").write_text("edgetime\nhexpire\ninfofix\n")
    (OUT / "differ-seeds.txt").write_text("7\n19\n20\n23\n")
    for geometry in ("split", "armed-fused"):
        env = dict(REDIS74_ROOT="/home/user/Projects/redis74", GATE_LOAD_CORES="121-127",
                   GATE_DIFFER_ORACLE_CORES="120", GATE_DIFFER_GEOMETRY=geometry,
                   GATE_DIFFER_OUT=str(OUT / ("differ-" + geometry)),
                   GATE_DIFFER_PROOF_SUITES=str(OUT / "differ-suites.txt"),
                   GATE_DIFFER_PROOF_SEEDS=str(OUT / "differ-seeds.txt"))
        run(["tests/differ_gate.sh", ROOT / "build/tomokv", "25103", "25104", "112-119", "6:2"],
            "differ-" + geometry, env)


def audit():
    run(["python3", "tools/lbstall_artifacts.py", "compare", "build/perfex/pre/src", "build/src",
         OUT / "hot-tomo.json"], "hot-tomo")
    run(["python3", "tools/lbstall_artifacts.py", "compare", "build/perfex/pre/db0/src", "build/db0/src",
         OUT / "hot-db0.json"], "hot-db0")
    run(["python3", "tools/ccfix_audit.py", "build/perfex/pre", "build", OUT / "full"], "full")
    run(["python3", "docs/deadswitch/linked_bytes.py", "build/perfex/pre/tomokv", "build/tomokv",
         OUT / "linked.json"], "linked")


def main():
    global OUT
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("units", "correctness", "audit", "wiring"))
    p.add_argument("--output", type=Path, default=OUT,
                   help="new proof directory; preserve earlier attempts separately")
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(112, 128)), "proof escaped CPUs 112-127"
    OUT = a.output.resolve()
    assert OUT.is_relative_to(ROOT), "proof output escaped worktree"
    OUT.mkdir(parents=True, exist_ok=True)
    if a.stage == "wiring":
        run(["python3", "tests/gates_test.py"], "gates-test")
        run(["python3", "tests/gate_ledger_fixture.py"], "ledger")
        run(["python3", "docs/pfconfirm/test_confirm.py"], "pfconfirm-unit")
    else:
        globals()[a.stage]()
    return any(row["exit_code"] for row in RESULTS)


if __name__ == "__main__":
    raise SystemExit(main())
