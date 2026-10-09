#!/usr/bin/env python3
"""One delivery proof: existing units, witnessed ACL batteries, focused differential."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT / "tests"))
from gate_quiet import QuietMonitor, QuietViolation
from psfix import boot
from _differ_history import permanent_seeds

OUT = ROOT / "docs/aclkeys/delivery-proof"
DATA = ROOT / "build/aclkeys/delivery-proof"
OUT.mkdir(exist_ok=False)
DATA.mkdir(exist_ok=False)
results = {}


def now():
    return datetime.now(timezone.utc).isoformat()


def record(row):
    with (OUT / "commands.jsonl").open("a") as stream:
        stream.write(json.dumps(row) + "\n")


def run(name, argv, *, env=None, timeout=180):
    start = now()
    print(start, shlex.join(argv), flush=True)
    with (OUT / (name + ".txt")).open("w") as stream:
        stream.write(start + "\n$ " + shlex.join(argv) + "\n")
        stream.flush()
        proc = subprocess.run(argv, stdout=stream, stderr=subprocess.STDOUT,
                              env=dict(os.environ, **(env or {})), timeout=timeout)
        end = now()
        stream.write("\n" + end + " exit=" + str(proc.returncode) + "\n")
    record(dict(name=name, start=start, end=end, argv=argv, environment=env or {},
                returncode=proc.returncode))
    results[name] = proc.returncode
    print((OUT / (name + ".txt")).read_text(), end="", flush=True)
    return proc.returncode


record(dict(start=now(), revision=subprocess.check_output(
    ["git", "rev-parse", "HEAD"], text=True).strip(), base=subprocess.check_output(
    ["git", "merge-base", "HEAD", "origin/cpp"], text=True).strip(),
    affinity=sorted(os.sched_getaffinity(0))))
assert run("hashes", ["sha256sum", "-c", "docs/aclkeys/SHA256SUMS"]) == 0
assert run("post-copy", ["cmp", "build/aclkeys/POST/tomokv", "build/tomokv"]) == 0
# Preserve the audit's real nonzero exit; no mismatch is suppressed or allowed away.
run("registry-and-permissions", ["taskset", "-c", "112-127", "build/aclkeys/POST/aclkeys-unit"])

quiet = False
first_attempt = time.monotonic()
for attempt in range(4):
    # Initial attempt plus at most three retries, spread over ten minutes.
    retry_at = first_attempt + 200 * attempt
    while time.monotonic() < retry_at:
        time.sleep(min(10, retry_at - time.monotonic()))
    monitor = QuietMonitor(range(112, 120), range(120, 128), ports=(18540, 18541),
                           sample_artifact=OUT / ("quiet-%d-samples.jsonl" % attempt))
    try:
        monitor.preflight()
        quiet = True
    except QuietViolation as error:
        print(now(), "preflight refusal:", error, flush=True)
    finally:
        evidence = monitor.close()
        (OUT / ("quiet-%d.json" % attempt)).write_text(json.dumps(evidence, indent=2) + "\n")
    if quiet:
        print(now(), "quiet preflight PASS", flush=True)
        break

if quiet:
    for atomic in (0, 1):
        name = "witness-atomic-%d" % atomic
        directory = DATA / name
        directory.mkdir()
        aclfile = directory / "users.acl"
        aclfile.write_text("user default on nopass ~* &* +@all\n")
        argv = [str(ROOT / "build/aclkeys/POST/tomokv"), "--bind", "127.0.0.1",
                "--port", "18540", "--shards", "16", "--ratio", "6:2",
                "--atomic", str(atomic), "--dir", str(directory), "--save", "",
                "--aclfile", str(aclfile)]
        record(dict(name=name + "-boot", start=now(), argv=["taskset", "-c", "112-119", *argv]))
        with boot(argv, "112-119", 18540, OUT / (name + "-server.txt")):
            run(name, ["taskset", "-c", "120-127", "python3",
                       "docs/aclkeys/trace-witness.py", "127.0.0.1", "18540", str(aclfile)])
        record(dict(name=name + "-stop", end=now(), clean_shutdown=True))
    # The current harness requires every permanent seed, even for a deterministic suite.
    (OUT / "seeds.txt").write_text("".join(str(seed) + "\n" for seed in permanent_seeds()))
    (OUT / "suites.txt").write_text("aclkeys\n")
    env = dict(GATE_LOAD_CORES="120-127", GATE_DIFFER_ORACLE_CORES="120-127",
               GATE_DIFFER_OUT=str(DATA / "differ"),
               GATE_DIFFER_PROOF_SUITES=str(OUT / "suites.txt"),
               GATE_DIFFER_PROOF_SEEDS=str(OUT / "seeds.txt"))
    run("differ", ["taskset", "-c", "120-127", "bash", "tests/differ_gate.sh",
                   "build/aclkeys/POST/tomokv", "18540", "18541", "112-119", "6:2"],
        env=env, timeout=180)
    for path in (DATA / "differ").glob("*"):
        if path.is_file():
            shutil.copy2(path, OUT / ("differ-" + path.name))
else:
    results["live_proofs"] = "REFUSED: quiet preflight failed all four attempts"

(OUT / "results.json").write_text(json.dumps(dict(finished=now(), results=results), indent=2) + "\n")
print(json.dumps(results, indent=2), flush=True)
# A faithful delivery can contain red evidence; do not report this as an all-green suite.
sys.exit(int(any(value != 0 for value in results.values())))
