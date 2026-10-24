#!/usr/bin/env python3
"""Repeat a baseline failure once, with the complete original gate job."""
import json
import subprocess
import time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
while True:
    try:
        state = json.loads((DOC / "campaign-watch-state.json").read_text())
        ready = state.get("active") is None and state.get("completed") == state.get("planned") == 3
    except (FileNotFoundError, json.JSONDecodeError):
        ready = False
    if ready:
        break
    time.sleep(1)
argv = ["taskset", "-c", "96-111", "python3", str(DOC / "verify.py"), "gate",
        "--prefix", "pre-snapshot-repeat-", "--binary", str(ROOT / "build/pre-objects/build/tomokv"),
        "--source-root", str(ROOT / "build/pre-objects"), "--jobs", "snapshot-epoll"]
rc = subprocess.run(argv, cwd=ROOT).returncode
(DOC / "campaign-reruns-results.json").write_text(json.dumps(dict(argv=argv, returncode=rc), indent=2) + "\n")
raise SystemExit(rc)
