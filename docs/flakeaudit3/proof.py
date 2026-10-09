#!/usr/bin/env python3
"""Six serial complete differential jobs, then an independent full iteration.

Reuse the preceding audit's quiet budget and lossless log collector. Only refused
admissions are retried (initial screen plus three retries over ten minutes).
Any failed gate stops its campaign and its evidence is retained.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("flakeaudit2_proof", ROOT / "docs/flakeaudit2/proof.py")
prior = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prior)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("selected", "full"))
    args = parser.parse_args()
    os.chdir(ROOT)
    out = ROOT / "docs/flakeaudit3/evidence" / (
        args.stage + "-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    out.mkdir()
    jobs = (ROOT / "docs/flakeaudit3/jobs.txt").read_text().splitlines()
    command = ["taskset", "-c", "112-127", "tests/gate.sh", "iteration",
               "--server-cores", "112-119", "--load-cores", "120-127",
               "--server-smt", "", "--load-smt", "", "--ports", "18340-18342"]
    prior.write(out / "request.json", dict(stage=args.stage, command=command,
        repetitions=6 if args.stage == "selected" else 1,
        jobs=jobs if args.stage == "selected" else None,
        revision=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        origin=subprocess.check_output(["git", "rev-parse", "origin/cpp"], text=True).strip()))
    print("proof evidence: %s" % out, flush=True)
    if not prior.quiet(out):
        return 3
    # Always refresh after the final origin merge, even if an older binary exists.
    build = out / "build"
    build.mkdir()
    rc = prior.run(build, ["taskset", "-c", "112-127", "make", "-j16"])
    if rc:
        return rc
    for index in range(1, 7 if args.stage == "selected" else 2):
        run = out / ("run-%d" % index)
        run.mkdir()
        env = os.environ.copy()
        env.pop("GATE_ONLY_JOBS", None)
        env["GATE_LEDGER"] = str(run / "ledger")
        if args.stage == "selected":
            env["GATE_ONLY_JOBS"] = " ".join(jobs)
        rc = prior.run(run, command, env, gate=True)
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
