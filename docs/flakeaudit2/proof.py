#!/usr/bin/env python3
"""Serial, fail-closed extension of flakeaudit/repeat.sh. Never discard a failed run."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from gate_quiet import QuietMonitor


def write(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def quiet(out, prior=None):
    started = json.loads(prior.read_text())["started_at"] if prior else time.time()
    first = 1 if prior else 0
    # Initial screen and at most three retries, spread over ten minutes. These
    # are refused admissions, never retries of a failed battery or benchmark.
    for attempt in range(first, 4):
        while time.time() < started + attempt * 200:
            time.sleep(min(5, started + attempt * 200 - time.time()))
        monitor = QuietMonitor(set(range(112, 120)), set(range(120, 128)),
                               ports=[18340, 18341, 18342])
        accepted = False
        try:
            monitor.preflight()
            accepted = True
        except Exception as error:
            print("quiet admission %d REFUSED: %s" % (attempt + 1, error), flush=True)
        finally:
            write(out / ("quiet-%d.json" % (attempt + 1)), monitor.close())
        if accepted:
            print("quiet admission %d accepted" % (attempt + 1), flush=True)
            return True
    write(out / "refusal.json", dict(status="REFUSED", reason="quiet precondition",
                                   attempts=4, prior=str(prior) if prior else None))
    return False


def server_digest():
    server = ROOT / "build/tomokv"
    return hashlib.file_digest(server.open("rb"), "sha256").hexdigest() if server.exists() else None


def run(out, command, env=None, gate=False):
    before = server_digest()
    write(out / "invocation.json", dict(command=command, revision=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), origin=subprocess.check_output(
        ["git", "rev-parse", "origin/cpp"], text=True).strip(), started_at=time.time(),
        server_sha256_before=before, selected_jobs=(env or {}).get("GATE_ONLY_JOBS")))
    with (out / "run.log").open("w") as log:
        rc = subprocess.call(command, stdout=log, stderr=subprocess.STDOUT, env=env)
    # Preserve all textual gate evidence, including failed and partial jobs. Large
    # binaries, data files and build objects stay in build/, never in the receipt.
    roots = []
    for line in (out / "run.log").read_text(errors="replace").splitlines():
        if line.strip().startswith("artifacts:"):
            path = Path(line.split("artifacts:", 1)[1].strip())
            if path.is_dir() and path.parent == ROOT / "build":
                roots.append(path)
    for source in roots:
        import tarfile
        with tarfile.open(out / (source.name + ".tar.gz"), "w:gz") as archive:
            for path in sorted(source.rglob("*")):
                if path.is_file() and (path.suffix in (".log", ".txt", ".json", ".tsv", ".sh", ".err")
                                      or path.name in ("ledger", "timings", "done", "phases.tsv")):
                    archive.add(path, arcname=str(path.relative_to(source)))
    ledgers = list(out.glob("ledger*"))
    failures = [line for path in ledgers if path.is_file()
                for line in path.read_text(errors="replace").splitlines() if line.startswith("FAIL\t")]
    after = server_digest()
    if gate and (not before or before != after or not ledgers or failures or not roots):
        rc = rc or 1
    write(out / "result.json", dict(rc=rc, fail_rows=failures, server_sha256_after=after,
                                   run_ids=[p.name for p in roots], ended_at=time.time()))
    print("%s rc=%d FAIL rows=%d" % (out.name, rc, len(failures)), flush=True)
    return rc


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=("build", "selected", "full"))
    p.add_argument("--prior-screen", type=Path)
    args = p.parse_args()
    os.chdir(ROOT)
    base = ROOT / "docs/flakeaudit2/evidence" / (args.stage + "-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()))
    base.mkdir()
    command = ["taskset", "-c", "112-127", "tests/gate.sh", "iteration",
               "--server-cores", "112-119", "--load-cores", "120-127",
               "--server-smt", "", "--load-smt", "", "--ports", "18340-18342"]
    write(base / "request.json", dict(stage=args.stage, command=command,
        repetitions=6 if args.stage == "selected" else 1,
        jobs=(ROOT / "docs/flakeaudit2/jobs.txt").read_text().splitlines()
             if args.stage == "selected" else None))
    if not quiet(base, args.prior_screen):
        return 3
    if args.stage == "build":
        return run(base, ["taskset", "-c", "112-127", "make", "-j16"])
    if server_digest() is None:
        out = base / "build"
        out.mkdir()
        rc = run(out, ["taskset", "-c", "112-127", "make", "-j16"])
        if rc:
            return rc
    for index in range(1, 7 if args.stage == "selected" else 2):
        out = base / ("run-%d" % index)
        out.mkdir()
        env = os.environ.copy()
        env.pop("GATE_ONLY_JOBS", None)
        env["GATE_LEDGER"] = str(out / "ledger")
        if args.stage == "selected":
            env["GATE_ONLY_JOBS"] = " ".join((ROOT / "docs/flakeaudit2/jobs.txt").read_text().splitlines())
        rc = run(out, command, env, gate=True)
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
