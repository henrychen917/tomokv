#!/usr/bin/env python3
"""Check the final selected-job verdict, preserving superseded failures."""
import hashlib
import itertools
import json
from pathlib import Path


DOC = Path("docs/clientcompat")
VALIDATION = DOC / "validation"


def read(name):
    return json.loads((VALIDATION / (name + ".json")).read_text())


def check_at412_product(run):
    """Recheck raw legs, including the three oracle script forms per case."""
    cases = []
    forms = ("EVAL", "EVALSHA", "FCALL")
    names = ["T" + str(n) for n in range(1, 17) if n != 11] + ["T11a", "T11b"]
    for name in names:
        modes = ("2s",) if name in ("T3", "T10", "T11a") else ("1s", "2s")
        expected = {f"redis-redis-0-{form}" for form in forms}
        expected.update(f"{mode}-{engine}-{atomic}-{form}" for mode, engine, atomic, form
                        in itertools.product(modes, ("uring", "epoll"), (0, 1), forms))
        path = Path(run) / "jobs" / ("at412-" + name) / ("at412-" + name) / "results.json"
        rows = json.loads(path.read_text())
        assert len(rows) == len(expected) and {r["leg"] for r in rows} == expected, name
        assert all(r["pass"] and r["case"] == name for r in rows), name
        cases.append(dict(case=name, legs=len(rows), oracle_legs=len(forms), modes=list(modes),
                          engines=["uring", "epoll"], atomics=[0, 1], forms=list(forms),
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    product = dict(source="tests/at412.py declared matrix", run=run, cases=cases,
                   total_legs=sum(c["legs"] for c in cases), complete=True)
    assert product["total_legs"] == 423
    (VALIDATION / "at412-product.json").write_text(json.dumps(product, indent=2) + "\n")
    return product


def main():
    post_sha = hashlib.sha256(Path("build/clientcompat/POST/tomokv").read_bytes()).hexdigest()
    pad_sha = hashlib.sha256(Path("build/clientcompat/PAD-A/tomokv").read_bytes()).hexdigest()
    chosen = {}
    history = []
    sources = []
    # Every winning job uses the final binary, including the separately
    # completed full FLUSH-order job. Preserve earlier failures separately.
    for name in ("regression-final", "final-witnesses"):
        receipt = read(name)
        assert receipt["complete"] and not receipt["full_gate_receipt"], name
        assert receipt["arm"]["sha256"] == post_sha, name
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
    for job in read("subscription-ping-before")["jobs"]:
        if job["failed"]:
            assert job["job"] == "clientcompat-multi-controls" and job["failed"] == 1
            history.append(dict(receipt="subscription-ping-before", **job))
    assert sum(j["failed"] for j in history) == 7
    interrupted = [dict(receipt="before-subscription-ping-epoll", **job)
                   for job in read("before-subscription-ping-epoll")["jobs"] if job["failed"]]
    assert len(interrupted) == 1 and interrupted[0]["job"] == "differ-armed-1"
    assert interrupted[0]["failed"] == 2

    differential = []
    for engine in ("uring", "epoll"):
        receipt = read("differential-" + engine)
        assert receipt["complete"] and receipt["failed"] == 0
        assert receipt["arm"]["sha256"] == post_sha and receipt["arm"]["engine"] == engine
        parts = []
        for part, comparisons in (("split-0", 235), ("split-1", 239),
                                  ("armed-0", 230), ("armed-1", 234), ("equivalence", 16)):
            path = Path(receipt["run"]) / "jobs" / ("differ-" + part) / "differ/complete.json"
            complete = json.loads(path.read_text())
            assert complete["complete"] and complete["comparisons"] == comparisons, complete
            assert complete["seeds"][:4] == [7, 19, 20, 23] and len(complete["seeds"]) == 5
            logs = (sorted(path.parent.rglob("server.log")) if part == "equivalence" else
                    sorted(path.parent.glob("target-atomic-*.log")))
            assert len(logs) == (32 if part == "equivalence" else 1), (engine, part, logs)
            boots = []
            for log in logs:
                header = next(line for line in log.read_text().splitlines()
                              if line.startswith("tomokv-cpp:"))
                assert (", io_uring," if engine == "uring" else ", epoll,") in header, header
                boots.append(dict(path=str(log), header=header,
                                  sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
            complete["engine_boots"] = boots
            parts.append(complete)
        differential.append(dict(engine=engine, receipt="differential-" + engine, parts=parts))

    fresh = json.loads((DOC / "freshness.json").read_text())
    assert len(fresh) == 55 and all(r["exit"] == 0 for r in fresh)
    instruction = json.loads((DOC / "instruction-summary.json").read_text())
    assert instruction["commands"]["rows"] == 160 and instruction["commands"]["higher"] == 0
    assert instruction["sessions"]["rows"] == 128
    assert instruction["commands"]["post_server_sha256"] == post_sha
    assert instruction["sessions"]["post_server_sha256"] == post_sha
    witnesses = json.loads((DOC / "witnesses/summary.json").read_text())
    assert len(witnesses) == 10
    for witness in witnesses:
        oracle, candidate = witness["results"]["oracle"], witness["results"]["candidate"]
        assert oracle["passed"] == oracle["total"] == 1
        assert candidate["total"] == 32
        if witness["arm"] == "POST":
            assert candidate["passed"] == 32 and candidate["sha256"] == post_sha
        else:
            assert witness["arm"] == "PAD-A" and candidate["failed"] and candidate["sha256"] == pad_sha
    selftest = read("final-gates-test")
    assert selftest["exit"] == 0 and selftest["tests"] == 83 and selftest["quiet"]
    assert selftest["server_sha256"] == post_sha
    tcl = read("tcl-promotions")
    assert len(tcl["summary"]) == 2 and {r["mode"] for r in tcl["summary"]} == {"1s", "2s"}
    assert all(r["files"] == 37 and r["runs"] == 39 and r["manifest_errors"] == 0 and
               r["sha256"] == post_sha for r in tcl["summary"])
    assert len(tcl["promotions"]) == 6 and all(r["event"]["status"] == "ok" for r in tcl["promotions"])
    at412 = check_at412_product(read("regression-final")["run"])
    verdict = dict(partial=True, full_gate_receipt=False, sources=sources,
                   requested_jobs=len(expected), completed_jobs=len(chosen),
                   passed_rows=sum(j["passed"] for j in chosen.values()), failed_rows=0,
                   jobs=[chosen[k] for k in sorted(chosen)],
                   superseded_failures=history, interrupted_for_correction=interrupted,
                   differential=differential,
                   freshness_checks=len(fresh), instructions=instruction,
                   post_sha256=post_sha, pad_sha256=pad_sha, gates_tests=83,
                   tcl_runs=78, tcl_promotions=6, at412_legs=423)
    (VALIDATION / "final-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    print(json.dumps({k: verdict[k] for k in
          ("requested_jobs", "completed_jobs", "passed_rows", "failed_rows", "freshness_checks")}, indent=2))


if __name__ == "__main__":
    main()
