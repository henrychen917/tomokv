#!/usr/bin/env python3
"""Reproduce registered AT4-WOUND-1 on this lane's PRE/POST without a server."""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
PRE = ROOT / "build/protofix/pre-source"
OUT = ROOT / "docs/protofix/wound-window"
BUILD = ROOT / "build/protofix/wound-window"
OUT.mkdir(exist_ok=True)
BUILD.mkdir(exist_ok=True)
os.sched_setaffinity(0, set(range(16)))
source_files = ["tests/txnorder_wound_window.cc", "src/cmd/txn_group.inc",
                "src/cmd/multi.inc", "src/cmd/scatter_engine.inc", "src/cmd/xshard_commands.inc",
                "src/core/server.h", "src/core/ex_execute.inc"]
identity = {}
for name in source_files:
    before, after = (PRE / name).read_bytes(), (ROOT / name).read_bytes()
    assert before == after, name
    identity[name] = hashlib.sha256(after).hexdigest()
rows = []
for arm, base in (("pre", PRE), ("post", ROOT)):
    for namespace, target in (("normal", "build/txnorder-watch-unit"),
                              ("db0", "build/txnorder-watch-db0-unit")):
        recipe = subprocess.check_output(["make", "-j16", "-n", "-W", "tests/txnorder_watch_unit.cc", target], cwd=base, text=True)
        command = shlex.split(next(line for line in reversed(recipe.splitlines())
                                  if line.startswith("g++ ") and " -o " + target + " " in line))
        command[command.index("tests/txnorder_watch_unit.cc")] = "tests/txnorder_wound_window.cc"
        binary = BUILD / (arm + "-" + namespace)
        command[command.index("-o") + 1] = str(binary)
        with (OUT / (arm + "-" + namespace + "-build.log")).open("w") as log:
            subprocess.run(command, cwd=base, stdout=log, stderr=subprocess.STDOUT, check=True)
        for mode in ("1s", "2s"):
            result = subprocess.run([str(binary), mode], cwd=base, capture_output=True, text=True, timeout=60)
            text = result.stdout + result.stderr
            (OUT / (arm + "-" + namespace + "-" + mode + ".log")).write_text(text)
            witnessed = result.returncode == 1 and all(token in text for token in (
                "read_done=1 pre_epoch=0 aborted=1 no_such_key=1 source_present=1 commit_accepted=1 final_epoch=1",
                "FAIL: wounded group completed before cancellation publication; commit accepted"))
            rows.append(dict(arm=arm, namespace=namespace, mode=mode, command=command,
                             binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
                             exit=result.returncode, registered_defect_reproduced=witnessed, output=text))
            (OUT / "receipt.json").write_text(json.dumps(dict(
                defect="AT4-WOUND-1", source_files_identical_pre_post=identity, results=rows), indent=2) + "\n")
            print(arm, namespace, mode, "registered defect reproduced:", witnessed, flush=True)
assert len(rows) == 8 and all(row["registered_defect_reproduced"] for row in rows), rows
