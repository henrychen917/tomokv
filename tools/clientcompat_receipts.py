#!/usr/bin/env python3
"""Retain whole gate-job receipts without treating a partial run as a full gate."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--expected-jobs", type=Path, required=True)
    parser.add_argument("--allow-pending", action="store_true")
    args = parser.parse_args()
    output = Path("docs/clientcompat/validation")
    output.mkdir(parents=True, exist_ok=True)
    jobs = []
    raw = {}
    for job in sorted((args.run / "jobs").iterdir()):
        if not job.is_dir():
            continue
        done = job / "done"
        if not done.exists():
            assert args.allow_pending, f"unfinished job: {job.name}"
            continue
        status, passed, failed = map(int, done.read_text().split())
        ledger = (job / "ledger").read_text().splitlines()
        assert sum(line.startswith("ok\t") for line in ledger) == passed, job
        assert sum(line.startswith("FAIL\t") for line in ledger) == failed, job
        record = dict(job=job.name, exit=status, passed=passed, failed=failed, ledger=ledger)
        jobs.append(record)
        for name in ("done", "ledger", "timings", "output.log", "build.log"):
            path = job / name
            if path.is_file():
                raw[str(path.relative_to(args.run))] = path.read_text(errors="replace")
        for path in sorted(job.rglob("*.json")):
            rel = path.relative_to(job)
            if any(part in ("data", "checkout", "appendonlydir") for part in rel.parts):
                continue
            # Include private matrix declarations and all recorded legs. Each
            # runner retains its own non-vacuity and complete-product checks.
            raw[str(path.relative_to(args.run))] = json.loads(path.read_text())
        legs = job / "differ/legs.tsv"
        if legs.exists():
            raw[str(legs.relative_to(args.run))] = legs.read_text()
            record["differential_legs"] = len(legs.read_text().splitlines())
            # Retain startup engine/geometry declarations, including both
            # witness and replay servers for every equivalence cell.
            for path in sorted((job / "differ").rglob("*.log")):
                if path.name in ("server.log", "oracle.log") or path.name.startswith("target-atomic-"):
                    raw[str(path.relative_to(args.run))] = path.read_text(errors="replace")
    found = {job["job"] for job in jobs}
    expected = set(args.expected_jobs.read_text().split())
    missing = sorted(expected - found)
    assert args.allow_pending or not missing, missing
    for name in ("ledger.partial", "ledger.partial.timings", "plan.sh", "row-timeouts.json"):
        path = args.run / name
        if path.is_file():
            raw[name] = path.read_text()
    archive = output / (args.label + ".json.gz")
    archive.write_bytes(gzip.compress(json.dumps(raw, separators=(",", ":")).encode(), mtime=0))
    report = dict(run=str(args.run),partial=True,full_gate_receipt=False,
                  complete=not missing and len(jobs)==sum(p.is_dir() for p in (args.run/"jobs").iterdir()),
                  jobs=jobs,missing=missing,archive=str(archive),
                  archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
                  passed=sum(job["passed"] for job in jobs),failed=sum(job["failed"] for job in jobs))
    (output / (args.label + ".json")).write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k:v for k,v in report.items() if k not in ("jobs", "missing")},indent=2))


if __name__ == "__main__":
    main()
