#!/usr/bin/env python3
"""Summarize completed partial gate invocations without hiding failed attempts."""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
PREFIXES = (
    "post-final-v2-directed-", "pre-final-directed-", "pre-final-v2-",
    "post-related-", "post-eviction-", "pre-related-", "pre-eviction-",
    "post-differ-epoll", "post-differ-uring", "pre-differ-epoll", "pre-differ-uring",
    "post-storage-final-", "post-watch-related-", "pre-watch-related-",
    "post-repaired-", "pre-snapshot-repeat-",
)
results = []
for ledger in sorted(DOC.glob("*.ledger.partial")):
    if not ledger.name.startswith(PREFIXES):
        continue
    name = ledger.name.removesuffix(".ledger.partial")
    rc_path = DOC / (name + ".rc")
    if not rc_path.exists():
        continue
    lines = [line.split("\t", 2) for line in ledger.read_text().splitlines()]
    assert lines and lines[0][0] == "PARTIAL", ledger
    counts = collections.Counter(row[0] for row in lines[1:])
    result = dict(
        name=name,
        receipt_kind="partial diagnostic, not a full gate receipt",
        selector=lines[0][2],
        returncode=int(rc_path.read_text()),
        counts=dict(counts),
        failures=[row[2] for row in lines[1:] if row[0] != "ok"],
        ledger=str(ledger.relative_to(ROOT)),
        archive=str((DOC / (name + "-evidence.tar.gz")).relative_to(ROOT)),
    )
    results.append(result)
(DOC / "campaign-summary.json").write_text(json.dumps(results, indent=2) + "\n")
for result in results:
    print(result["name"], "exit", result["returncode"], result["counts"])
