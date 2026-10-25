#!/usr/bin/env python3
"""Finish the WATCH grep coverage after the first serialized campaign."""
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
while True:
    state = json.loads((DOC / "campaign-state.json").read_text())
    if state.get("active") is None and state.get("completed") == state.get("planned"):
        break
    time.sleep(1)

jobs = json.loads((DOC / "required-jobs.json").read_text())
steps = [
    ("post-storage-final-", ROOT / "build/tomokv", jobs["post_rerun"], None),
    ("post-watch-related-", ROOT / "build/tomokv", jobs["watch_related"], None),
    ("pre-watch-related-", ROOT / "build/pre-objects/build/tomokv", jobs["watch_related"], ROOT / "build/pre-objects"),
]
results = []
for prefix, binary, selected, source in steps:
    if (ROOT / "build/datafix2/stop-after-current").exists():
        break
    argv = ["taskset", "-c", "96-111", "python3", str(DOC / "verify.py"), "gate",
            "--prefix", prefix, "--binary", str(binary), "--jobs", selected]
    if source:
        argv += ["--source-root", str(source)]
    (DOC / "campaign-watch-state.json").write_text(json.dumps(dict(active=prefix, argv=argv), indent=2) + "\n")
    rc = subprocess.run(argv, cwd=ROOT).returncode
    results.append(dict(prefix=prefix, driver_returncode=rc))
    (DOC / "campaign-watch-results.json").write_text(json.dumps(results, indent=2) + "\n")
(DOC / "campaign-watch-state.json").write_text(json.dumps(dict(active=None, completed=len(results), planned=len(steps))) + "\n")
