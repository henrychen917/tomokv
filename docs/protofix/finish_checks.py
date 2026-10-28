#!/usr/bin/env python3
"""Serialize the remaining checks after the main matrix has released its slot."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
parser = argparse.ArgumentParser()
parser.add_argument("--after-pid", type=int)
args = parser.parse_args()
if args.after_pid:
    # The PID must currently name this worktree's matrix, not an arbitrary job.
    command = Path(f"/proc/{args.after_pid}/cmdline").read_bytes().split(b"\0")
    assert command[:2] == [b"python3", b"docs/protofix/matrix.py"], command
    assert Path(f"/proc/{args.after_pid}/cwd").resolve() == ROOT
    while Path(f"/proc/{args.after_pid}").exists():
        time.sleep(2)
results = []
commands = [
    ("supplement", ["python3", "docs/protofix/supplement.py"]),
    ("pad-control", ["python3", "docs/protofix/run_jobs.py", "verified-pad-control", "inline_quoted", "netio-1s", "netio-2s",
                     "--binary", "build/tomokv-protofix-PAD-A"]),
    ("pipeorder", ["python3", "docs/protofix/pipeorder.py"]),
    ("gate-selftests", ["python3", "tests/gates_test.py"]),
    ("production-freshness", ["python3", "docs/protofix/production_build.py"]),
]
for name, command in commands:
    logfile = ROOT / "build/protofix" / (name + "-verified.log")
    assert not logfile.exists(), "retain every earlier attempt"
    with logfile.open("w") as log:
        result = subprocess.run(command, cwd=ROOT, env=dict(os.environ, GATE_TEST_PORT="20398"),
                                stdout=log, stderr=subprocess.STDOUT)
    results.append(dict(name=name, command=command, exit=result.returncode, log=str(logfile)))
    (ROOT / "docs/protofix/finish-results.json").write_text(json.dumps(results, indent=2) + "\n")
    print(name, result.returncode, flush=True)
# PAD's four imported rows must fail, with seven valid cases rejected per row.
receipt = json.loads((ROOT / "docs/protofix/jobs/verified-pad-control.json").read_text())
directory = Path(receipt["artifacts"])
for mode in ("1s", "2s"):
    for engine in ("epoll", "uring"):
        text = (directory / "jobs/inline_quoted" / (mode + "-" + engine + ".log")).read_text()
        assert "inline decoding: 7 cases, 7 failures" in text, text
ledger = (ROOT / "docs/protofix/jobs/verified-pad-control.tsv.partial").read_text().splitlines()
assert sum(line.startswith("FAIL\t") for line in ledger) == 4, ledger
assert all("inline quoted argument decoding" in line for line in ledger if line.startswith("FAIL\t")), ledger
assert all(row["exit"] == (1 if row["name"] == "pad-control" else 0) for row in results), results
