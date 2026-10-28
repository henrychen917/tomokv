#!/usr/bin/env python3
"""Whole gate jobs on CPUs 0-15 / ports 20300-20399; retain every attempt."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("name")
parser.add_argument("jobs", nargs="+")
parser.add_argument("--engine", choices=("uring", "epoll"), default="uring")
parser.add_argument("--fused", action="store_true")
parser.add_argument("--binary", default="build/tomokv")
parser.add_argument("--asan-binary")
args = parser.parse_args()
assert not set(args.jobs) & {"atomic_floor", "flip_saturated", "efficiency"}, "performance remains maintainer work"
os.sched_setaffinity(0, set(range(16)))
out = ROOT / "docs/protofix/jobs"
out.mkdir(parents=True, exist_ok=True)
log = out / (args.name + ".log")
assert not log.exists(), "preserve the earlier attempt"
binary = (ROOT / args.binary).resolve()
env = dict(os.environ, REDIS74_ROOT="/home/user/Projects/redis",
           GATE_DIFFER_ORACLE_BIN="/home/user/Projects/redis74/src/redis-server",
           GATE_DIFFER_REDIS_CLI="/home/user/Projects/redis74/src/redis-cli",
           GATE_ONLY_JOBS=" ".join(args.jobs), GATE_NET_IO=args.engine,
           GATE_PROOF_NET_IO=args.engine, GATE_ZC_NET_IO=args.engine,
           GATE_DIFFER_NET_IO=args.engine, GATE_TXN_FUSED=str(int(args.fused)),
           GATE_PROOF_NO_RATES="1",
           GATE_TEST_PORT="20398", GATE_LEDGER=str(out / (args.name + ".tsv")))
if args.asan_binary:
    env["GATE_ASAN_BINARY"] = str((ROOT / args.asan_binary).resolve())
argv = ["bash", "tests/gate.sh", "iteration", "--server-cores", "0-7", "--server-smt", "",
        "--load-cores", "8-15", "--load-smt", "", "--ports", "20300-20329", "--candidate-binary", str(binary)]
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
receipt = dict(argv=argv, env={k: v for k, v in env.items() if k.startswith("GATE_") or k == "REDIS74_ROOT"},
               binary_sha256=sha(binary), gate_sha256=sha(ROOT / "tests/gate.sh"),
               commit=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), started=time.time())
with log.open("w") as stream:
    result = subprocess.run(argv, cwd=ROOT, env=env, stdout=stream, stderr=subprocess.STDOUT)
text = log.read_text()
match = re.search(r"  artifacts: (.+)", text)
receipt.update(exit=result.returncode, seconds=time.time() - receipt["started"],
               binary_unchanged=sha(binary) == receipt["binary_sha256"],
               artifacts=match[1] if match else None,
               summary=[line for line in text.splitlines() if line.startswith("GATE(PARTIAL)")])
(out / (args.name + ".json")).write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt), flush=True)
raise SystemExit(result.returncode)
