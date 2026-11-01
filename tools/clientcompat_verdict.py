#!/usr/bin/env python3
"""Check the final selected-job verdict, preserving superseded failures."""
import hashlib
import json
from pathlib import Path


DOC = Path("docs/clientcompat")
VALIDATION = DOC / "validation"


def read(name):
    return json.loads((VALIDATION / (name + ".json")).read_text())


def main():
    chosen = {}
    history = []
    sources = []
    # Every winning job uses the final binary, including the separately
    # completed full FLUSH-order job. Preserve earlier failures separately.
    for name in ("regression-final", "ack-trackorder", "final-witnesses", "final-core-units"):
        receipt = read(name)
        assert receipt["complete"] and not receipt["full_gate_receipt"], name
        archive = Path(receipt["archive"])
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == receipt["archive_sha256"]
        sources.append(dict(receipt=name, archive_sha256=receipt["archive_sha256"]))
        for job in receipt["jobs"]:
            assert job["exit"] == job["failed"] == 0, (name, job)
            chosen[job["job"]] = dict(receipt=name, **job)
    for name in ("before-ack-wake-regression", "before-ack-wake-extra"):
        for job in read(name)["jobs"]:
            if job["exit"] or job["failed"]:
                assert job["job"] in ("feature-split-0", "feature-armed-0", "trackorder", "blockfix2"), job
                history.append(dict(receipt=name, **job))
    expected = set()
    for name in ("final-regression-jobs.txt", "supplement-jobs.txt", "coverage-extra-jobs.txt"):
        expected.update((DOC / name).read_text().split())
    assert not expected - chosen.keys(), sorted(expected - chosen.keys())
    assert all(j["exit"] == j["failed"] == 0 for j in chosen.values())
    assert sum(j["failed"] for j in history) == 6, history

    differential = []
    for engine in ("uring", "epoll"):
        receipt = read("differential-" + engine)
        assert receipt["complete"] and receipt["failed"] == 0
        parts = []
        for part, comparisons in (("split-0", 235), ("split-1", 239),
                                  ("armed-0", 230), ("armed-1", 234), ("equivalence", 16)):
            path = Path(receipt["run"]) / "jobs" / ("differ-" + part) / "differ/complete.json"
            complete = json.loads(path.read_text())
            assert complete["complete"] and complete["comparisons"] == comparisons, complete
            assert complete["seeds"][:4] == [7, 19, 20, 23] and len(complete["seeds"]) == 5
            parts.append(complete)
        differential.append(dict(engine=engine, receipt="differential-" + engine, parts=parts))

    fresh = json.loads((DOC / "freshness.json").read_text())
    assert len(fresh) == 55 and all(r["exit"] == 0 for r in fresh)
    instruction = json.loads((DOC / "instruction-summary.json").read_text())
    assert instruction["commands"]["rows"] == 160 and instruction["commands"]["higher"] == 0
    assert instruction["sessions"]["rows"] == 128
    verdict = dict(partial=True, full_gate_receipt=False, sources=sources,
                   requested_jobs=len(expected), completed_jobs=len(chosen),
                   passed_rows=sum(j["passed"] for j in chosen.values()), failed_rows=0,
                   jobs=[chosen[k] for k in sorted(chosen)],
                   superseded_failures=history, differential=differential,
                   freshness_checks=len(fresh), instructions=instruction)
    (VALIDATION / "final-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps({k: verdict[k] for k in
          ("requested_jobs", "completed_jobs", "passed_rows", "failed_rows", "freshness_checks")}, indent=2))


if __name__ == "__main__":
    main()
