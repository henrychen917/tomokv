#!/usr/bin/env python3
"""Index actual completed gate jobs and differential legs; never invent verdicts."""
import argparse
import collections
import json
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/datafix2"
sys.path.insert(0, str(ROOT / "tests"))
from differ_fanout import expected_legs

parser = argparse.ArgumentParser()
parser.add_argument("--require-complete", action="store_true")
args = parser.parse_args()

# Later completed invocations supersede earlier attempts for the same whole job.
# All failed attempts remain available in campaign-summary.json and their archives.
ARMS = {
    "POST": ["post-final-v2-directed-gate", "post-related-gate", "post-eviction-gate",
             "post-repaired-gate", "post-storage-final-gate", "post-watch-related-gate"],
    "PRE": ["pre-final-directed-gate", "pre-final-v2-gate", "pre-related-gate",
            "pre-eviction-gate", "pre-watch-related-gate", "pre-snapshot-repeat-gate"],
}
requested = json.loads((DOC / "required-jobs.json").read_text())
required = sorted(set(" ".join(requested[k] for k in
    ("directed", "related", "eviction", "watch_related")).split()))

def archive(name):
    path = DOC / (name + "-evidence.tar.gz")
    return tarfile.open(path, "r:gz") if path.exists() and (DOC / (name + ".rc")).exists() else None

def read(tar, name):
    stream = tar.extractfile(name)
    assert stream is not None, name
    return stream.read().decode()

summary = {"required_jobs_per_arm": required, "arms": {}, "differential": []}
for arm, names in ARMS.items():
    jobs = {}
    for name in names:
        tar = archive(name)
        if tar is None:
            continue
        with tar:
            for member in tar.getnames():
                parts = member.split("/")
                if len(parts) != 3 or parts[0] != "jobs" or parts[2] != "done":
                    continue
                job = parts[1]
                done = list(map(int, read(tar, member).split()))
                rows = [line.split("\t", 2) for line in read(tar, f"jobs/{job}/ledger").splitlines()]
                counts = dict(collections.Counter(row[0] for row in rows))
                assert done[1:] == [counts.get("ok", 0), counts.get("FAIL", 0)], (name, job)
                jobs[job] = dict(invocation=name, completion=done, counts=counts,
                                 failures=[row[2] for row in rows if row[0] != "ok"])
    summary["arms"][arm] = dict(jobs=jobs, missing=[job for job in required if job not in jobs])

for arm in ("POST", "PRE"):
    for engine in ("epoll", "uring"):
        name = arm.lower() + "-differ-" + engine
        tar = archive(name)
        if tar is None:
            continue
        with tar:
            inventory = set(tar.getnames())
            plan = json.loads(read(tar, "differ-plan.json"))
            parts = []
            for part in ("split-0", "split-1", "armed-0", "armed-1"):
                folder = f"jobs/differ-{part}/differ/"
                rows = [line.split("\t") for line in read(tar, folder + "legs.tsv").splitlines()]
                actual = [(row[0], *map(int, row[1:4])) for row in rows]
                expected = expected_legs(plan, part)
                parts.append(dict(part=part, expected=len(expected), executed=len(rows),
                    inventory_matches=actual == expected, failed=[row for row in rows if row[4] != "0"],
                    completion=json.loads(read(tar, folder + "complete.json"))
                        if folder + "complete.json" in inventory else None))
            equivalence = []
            for seed in plan["equivalence_seeds"]:
                path = f"jobs/differ-equivalence/differ/mode-equivalence-{seed}/results.json"
                equivalence.append(dict(seed=seed, results=json.loads(read(tar, path)) if path in inventory else None))
            folds = {group: json.loads(read(tar, f"differ-{group}-fold.json"))
                     for group in ("split", "armed") if f"differ-{group}-fold.json" in inventory}
            summary["differential"].append(dict(arm=arm, engine=engine, invocation=name,
                permanent_seeds=plan["manifest"]["permanent"], seeds=plan["manifest"]["seeds"],
                parts=parts, equivalence=equivalence, folds=folds,
                aggregate_folds="not run by partial selector" if not folds else "present",
                returncode=int((DOC / (name + ".rc")).read_text())))

(DOC / "proof-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
for arm, result in summary["arms"].items():
    print(arm, len(required) - len(result["missing"]), "of", len(required), "whole jobs complete;",
          len(result["missing"]), "pending")
for result in summary["differential"]:
    print(result["arm"], result["engine"], sum(p["executed"] for p in result["parts"]), "differential legs",
          "receipt exit", result["returncode"], "aggregate folds:", result["aggregate_folds"])

if args.require_complete:
    assert all(not arm["missing"] for arm in summary["arms"].values()), "missing whole gate jobs"
    assert len(summary["differential"]) == 4, "missing differential engine or arm"
    assert all(part["inventory_matches"] for result in summary["differential"] for part in result["parts"]), "missing differential legs"
    post = summary["arms"]["POST"]["jobs"]
    assert all(post[job]["completion"][0] == 0 and not post[job]["failures"] for job in required), "POST has an unresolved failure"
    assert all(result["returncode"] == 0 and
               all(part["completion"] and not part["failed"] for part in result["parts"]) and
               all(eq["results"] and all(row.get("verdict") == "ok" for row in eq["results"])
                   for eq in result["equivalence"])
               for result in summary["differential"]), "differential job did not pass"
