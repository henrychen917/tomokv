#!/usr/bin/env python3
"""Collect completed blockfix gate receipts without starting any workload."""
import collections
import hashlib
import json
from pathlib import Path
import re
import tarfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/blockfix"
report = {}
for log in sorted(OUT.glob("*gate.log")):
    text = log.read_text(errors="replace")
    match = re.search(r"artifacts: (.+)", text)
    if not match:
        continue
    run = Path(match[1])
    if "GATE(PARTIAL):" not in text:
        report[log.name] = {"run": str(run), "complete": False}
        continue
    ledger = run / "ledger.partial"
    rows = [line.split("\t", 2) for line in ledger.read_text().splitlines()
            if line.startswith(("ok\t", "FAIL\t"))]
    item = dict(run=str(run), complete=True, rows=len(rows),
                verdicts=dict(collections.Counter(r[0] for r in rows)),
                failures=[r[2] for r in rows if r[0] == "FAIL"], directed={}, differential={})
    for job in sorted((run / "jobs").iterdir()):
        if job.name.startswith("blockfix_"):
            case = job.name.removeprefix("blockfix_")
            legs = sorted(job.glob(f"{case}-db*.log"))
            item["directed"][case] = dict(
                legs=len(legs), passed=sum(f"PASS {case}" in p.read_text() for p in legs),
                oracle_legs=sum("ORACLE 7.4.10" in p.read_text() for p in legs),
                names=[p.name for p in legs])
        legs = job / "differ/legs.tsv"
        if legs.exists():
            data = [line.split("\t") for line in legs.read_text().splitlines()]
            item["differential"][job.name] = dict(
                legs=len(data), seeds=sorted({int(r[2]) for r in data}),
                failed=[r for r in data if r[4] != "0"],
                climon=[r for r in data if r[0] == "climon"])
    archive = OUT / (log.stem + "-receipts.tar.gz")
    with tarfile.open(archive, "w:gz") as tar:
        for path in sorted(run.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix in (".log", ".txt", ".json", ".tsv", ".csv", ".timings", ".sh") or path.name in (
                    "ledger", "ledger.partial", "timings", "done", "instructions.log"):
                tar.add(path, arcname=str(path.relative_to(run)))
    item["archive"] = archive.name
    item["archive_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    report[log.name] = item
(OUT / "gate-receipts.json").write_text(json.dumps(report, indent=2) + "\n")
for name, item in report.items():
    print(name, item.get("verdicts", "INCOMPLETE"), item.get("failures", []))

focused = {}
proof = ROOT / "build/blockfix/climon"
for directory in sorted(proof.glob("climon-*")):
    seed_file = directory / "proof-seeds.json"
    if not seed_file.exists():
        continue
    seeds = json.loads(seed_file.read_text())["seeds"]
    cases = []
    for atomic in (0, 1):
        for seed in seeds:
            path = directory / f"climon-a{atomic}-s{seed}.txt"
            text = path.read_text(errors="replace") if path.exists() else ""
            cases.append(dict(atomic=atomic, seed=seed, passed="0 diffs -> PASS" in text,
                              has_coverage=Path(str(path)+".coverage.json").exists()))
    focused[directory.name] = dict(expected=2*len(seeds), cases=cases)
(OUT / "climon-receipts.json").write_text(json.dumps(focused, indent=2) + "\n")
with tarfile.open(OUT / "climon-receipts.tar.gz", "w:gz") as tar:
    for path in sorted(proof.rglob("*")):
        if path.is_file() and path.suffix in (".json", ".txt", ".log"):
            tar.add(path, arcname=str(path.relative_to(proof)))
