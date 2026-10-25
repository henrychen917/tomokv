#!/usr/bin/env python3
"""Read-only progress from the gate's own journals."""
import collections
import json
import re
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
for filename in ("campaign-state.json", "campaign-watch-state.json"):
    try:
        state = json.loads((DOC / filename).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        continue
    print(filename, state.get("active") or f"completed {state.get('completed')}/{state.get('planned')}")
for log in sorted(DOC.glob("*-differ-*.log")):
    paths = re.findall(r"(?:/[^\s:]+/)?build/gate-run\.[A-Za-z0-9]+", log.read_text())
    if not paths:
        continue
    run = Path(paths[0])
    if not run.is_absolute():
        run = ROOT / run
    if not run.exists():
        continue
    if (DOC / (log.stem + ".rc")).exists():
        continue
    print(log.stem)
    for job in sorted((run / "jobs").iterdir()):
        if not job.name.startswith("differ-"):
            continue
        journal = job / "differ/legs.tsv"
        if journal.exists() and job.name != "differ-equivalence":
            rows = [line.split("\t") for line in journal.read_text().splitlines()]
            rows = [row for row in rows if len(row) == 6]
            print(" ", job.name, "DONE" if (job / "done").exists() else "RUNNING",
                  len(rows), "legs", sum(row[4] != "0" for row in rows), "failed")
        else:
            print(" ", job.name, (job / "done").read_text().strip() if (job / "done").exists() else "RUNNING")

for pattern in ("*-watch-related-gate.log", "pre-snapshot-repeat-gate.log"):
    for log in sorted(DOC.glob(pattern)):
        paths = re.findall(r"(?:/[^\s:]+/)?build/gate-run\.[A-Za-z0-9]+", log.read_text())
        if not paths:
            continue
        run = Path(paths[0])
        if not run.is_absolute():
            run = ROOT / run
        if not run.exists():
            continue
        jobs = sorted((run / "jobs").iterdir())
        print(log.stem, sum((job / "done").exists() for job in jobs), "finished jobs,", len(jobs), "started")
        for job in jobs:
            if not (job / "done").exists():
                print("  RUNNING", job.name)
            ledger = job / "ledger"
            if ledger.exists():
                for row in ledger.read_text().splitlines():
                    if row.startswith("FAIL\t"):
                        print(" ", job.name, row)
