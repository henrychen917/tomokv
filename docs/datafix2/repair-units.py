#!/usr/bin/env python3
"""Rebuild fixture changes between gate lifetimes, then repeat their whole jobs."""
import hashlib
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
while True:
    try:
        state = json.loads((DOC / "campaign-state.json").read_text())
    except (OSError, json.JSONDecodeError):
        time.sleep(1)
        continue
    if state.get("active") is None and state.get("completed") == 2:
        break
    time.sleep(1)

for prefix, source in (("post-final-", ROOT), ("pre-final-", ROOT / "build/pre-objects")):
    argv = ["taskset", "-c", "96-111", "python3", str(DOC / "build-units.py"),
            "--prefix", prefix, "--source-root", str(source)]
    subprocess.run(argv, cwd=ROOT, check=True)
    result = json.loads((DOC / (prefix + "unit-build.json")).read_text())
    assert result["build_returncode"] == 0 and all(row["returncode"] == 0 for row in result["checks"]), result

for arm, expected in json.loads((DOC / "binary-sha256.json").read_text()).items():
    actual = hashlib.file_digest((ROOT / expected["path"]).open("rb"), "sha256").hexdigest()
    assert actual == expected["sha256"], (arm, "server changed while rebuilding units", actual)

subprocess.run(["taskset", "-c", "96-111", "python3", str(DOC / "script-apply-oracle.py")], cwd=ROOT, check=True)
selected = "atomic_units debug-0 debug-1 fused-0 fused-1 txn_group_fused txn_group_split txnorder2"
subprocess.run(["taskset", "-c", "96-111", "python3", str(DOC / "verify.py"), "gate",
                "--prefix", "post-repaired-", "--binary", str(ROOT / "build/tomokv"),
                "--jobs", selected], cwd=ROOT, check=True)
assert (DOC / "post-repaired-gate.rc").read_text().strip() == "0", "repaired jobs failed; retain stop marker"
(ROOT / "build/datafix2/stop-after-current").unlink()
subprocess.run(["taskset", "-c", "96-111", "python3", str(DOC / "campaign.py"), "--resume"], cwd=ROOT, check=True)
