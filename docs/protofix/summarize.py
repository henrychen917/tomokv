#!/usr/bin/env python3
"""Validate finished proof receipts and write one reviewable coverage index."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/protofix"
os.sched_setaffinity(0, set(range(16)))
sys.path.insert(0, str(ROOT / "tests"))
import differ_fanout
read = lambda path: json.loads(path.read_text())
matrix, results = read(DOC / "matrix.json"), read(DOC / "matrix-results.json")
assert [row["name"] for row in results] == [row["name"] for row in matrix["batches"]]
assert all(row["exit"] in (0, 1) for row in results), results
supplement = read(DOC / "supplement-results.json")
assert len(supplement) == 5 and all(row["exit"] in (0, 1) for row in supplement), supplement
finish = read(DOC / "finish-results.json")
assert len(finish) == 5
assert all(row["exit"] in (0, 1) for row in finish), finish
post = hashlib.sha256((ROOT / "build/tomokv").read_bytes()).hexdigest()
assert post == matrix["post_sha256"]
names = [row["name"] for row in results] + [row["name"] for row in supplement if "jobs" in row]
batches = []
failed_post_rows = []
pre_sha = read(DOC / "pad-a.json")["arms"]["PRE"]["sha256"]
for name in names:
    receipt = read(DOC / "jobs" / (name + ".json"))
    baseline = name == "verified-debug1-fused-uring-pre"
    assert receipt["binary_unchanged"] and receipt["binary_sha256"] == (pre_sha if baseline else post)
    counts = re.search(r"GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL", receipt["summary"][0])
    assert counts and receipt["exit"] == int(int(counts[2]) > 0), receipt
    failures = [line for line in (DOC / "jobs" / (name + ".tsv.partial")).read_text().splitlines()
                if line.startswith("FAIL\t")]
    assert len(failures) == int(counts[2]), (name, failures)
    if not baseline:
        failed_post_rows += [dict(batch=name, row=line) for line in failures]
    batches.append(dict(name=name, passed=int(counts[1]), failed=int(counts[2]), seconds=receipt["seconds"],
                        arm="PRE" if baseline else "POST", failures=failures,
                        artifacts=receipt["artifacts"], gate_sha256=receipt["gate_sha256"]))
oracle = []
for engine in ("uring", "epoll"):
    receipt = read(DOC / "jobs" / ("verified-protocol-" + engine + ".json"))
    folder = Path(receipt["artifacts"]) / "jobs/respcompat"
    for mode, atomic, lane, reorder, databases in itertools.product(("1s", "2s"), (0, 1), (0, 1), (0, 1), (1, 16)):
        name = f"gate-inline-{mode}-a{atomic}-rl{lane}-r{reorder}-db{databases}.txt"
        text = (folder / name).read_text()
        assert "Redis 7.4.10: 148/148" in text and "TomoKV: 148/148" in text and "FAIL" not in text, name
        hit = re.search(r"decoded-key read-local witness: (\d+) hits", text)
        assert not lane or hit and int(hit[1]) > 0, name
        oracle.append(dict(engine=engine, mode=mode, atomic=atomic, read_local=lane, reorder=reorder,
                           databases=databases, cases_per_endpoint=148, read_local_hits=int(hit[1]) if hit else 0))
assert len(oracle) == 64
differential = []
for engine in ("uring", "epoll"):
    receipt = read(DOC / "jobs" / ("verified-differ-" + engine + ".json"))
    folder = Path(receipt["artifacts"])
    plan = read(folder / "differ-plan.json")
    assert plan["manifest"]["permanent"] == [7, 19, 20, 23]
    assert len(plan["suites"]) == 47 and plan["repeats"] == 4
    parts = []
    for part in ("split-0", "split-1", "armed-0", "armed-1", "equivalence"):
        result = read(folder / ("jobs/differ-" + part) / "differ/complete.json")
        assert result["complete"] and result["seeds"] == plan["manifest"]["seeds"]
        directory = folder / ("jobs/differ-" + part) / "differ"
        # Use the gate's own full journal validator, including SORT's declared
        # split-only geometry and positive per-command comparison witnesses.
        expected = (differ_fanout.check_equivalence(plan, directory) if part == "equivalence" else
                    differ_fanout.check_matrix(plan, part, directory))
        assert result["comparisons"] == expected, (engine, part, result)
        if part.startswith("armed-"):
            log = (directory.parent / "output.log").read_text()
            assert log.count("SKIP (suite requires the split 6:2 geometry)") == len(plan["manifest"]["seeds"])
        parts.append(dict(**result, declared_exclusions=["sort: split-only 6:2 geometry"]
                          if part.startswith("armed-") else []))
    differential.append(dict(engine=engine, plan=plan, parts=parts))
wound = read(DOC / "wound-window/receipt.json")
assert read(DOC / "wound-status.json")["diagnostic_exit"] == 0
assert len(wound["results"]) == 8 and all(row["registered_defect_reproduced"] for row in wound["results"])
assert {(row["arm"], row["namespace"], row["mode"]) for row in wound["results"]} == set(
    itertools.product(("pre", "post"), ("normal", "db0"), ("1s", "2s")))
counts = read(DOC / "instructions-final/comparison.json")
assert len(counts) == 24 and all(row["delta"] == 0 and row["functions_equal"] and row["external_calls_equal"] for row in counts)
identity = read(DOC / "linked-identity-frozen.json")
assert identity["post_sha256"] == post and not identity["hot_changed"]
build = read(DOC / "production/receipt.json")
assert build["before_sha256"] == build["after_sha256"] == post
assert len(build["freshness"]) == 49 and all(row["exit"] == 0 for row in build["builds"] + build["freshness"])
pipe = read(DOC / "pipeorder/receipt.json")
assert len(pipe["results"]) == 4 and all(row["passed"] for row in pipe["results"])
tcl = read(DOC / "tcl-protocol.json")
assert len(tcl["rows"]) == 2 and all(row["exit"] == 0 for row in tcl["rows"])
tcl_spec = read(ROOT / "tests/redis_tcl_passing.json")["files"]["unit/protocol"]
for arm in tcl["rows"]:
    assert arm["summary"]["binary_sha256"] == post and len(arm["summary"]["rows"]) == 1
    result = arm["summary"]["rows"][0]
    assert result["file"] == "unit/protocol" and result["complete"]
    assert result["passed"] == len(tcl_spec["passed_tests"]) == 17 and result["failed"] == 0
    assert result["skip_tests"] == sorted(tcl_spec["skip_tests"]) and result["skipped"] == 8
    assert result["exit_code"] == result["server_exit"] == 0 and not result["setup_errors"]
pad = read(DOC / "jobs/verified-pad-control.json")
assert pad["binary_unchanged"] and pad["exit"] == 1
assert pad["binary_sha256"] == read(DOC / "pad-a.json")["arms"]["PAD-A"]["sha256"]
ledger = (DOC / "jobs/verified-pad-control.tsv.partial").read_text().splitlines()
negative = [line for line in ledger if line.startswith("FAIL\t")]
assert len(negative) == 4 and all("inline quoted argument decoding" in line for line in negative)
for mode, engine in itertools.product(("1s", "2s"), ("epoll", "uring")):
    text = (Path(pad["artifacts"]) / "jobs/inline_quoted" / (mode + "-" + engine + ".log")).read_text()
    assert "inline decoding: 7 cases, 7 failures" in text
pre_inline = ROOT / "build/gate-run.EmQy06"
pre_plan = (pre_inline / "plan.sh").read_text()
assert "CANDIDATE_BINARY=" + str(ROOT / "build/protofix/pre-source/build/tomokv") in pre_plan
assert hashlib.sha256((ROOT / "build/protofix/pre-source/build/tomokv").read_bytes()).hexdigest() == pre_sha
pre_negative = [line for line in (pre_inline / "ledger.partial").read_text().splitlines()
                if line.startswith("FAIL\t")]
assert len(pre_negative) == 4 and all("inline quoted argument decoding" in line for line in pre_negative)
for mode, engine in itertools.product(("1s", "2s"), ("epoll", "uring")):
    text = (pre_inline / "jobs/inline_quoted" / (mode + "-" + engine + ".log")).read_text()
    assert "inline decoding: 7 cases, 7 failures" in text
gate_test = (ROOT / "build/protofix/gate-selftests-verified.log").read_text()
assert re.search(r"Ran 73 tests", gate_test) and re.search(r"^OK$", gate_test, re.M), gate_test[-2000:]
summary = dict(post_sha256=post, batches=batches, oracle=oracle, differential=differential,
               registered_wound_defect=wound,
               all_post_attempts_clean=not failed_post_rows, failed_post_rows=failed_post_rows,
               command_scope_exact_pairs=len(counts), hot_groups_equal=identity["hot_groups"],
               build_freshness_checks=len(build["freshness"]), gate_selftests=73,
               pre_inline_expected_failed_rows=pre_negative, pad_expected_failed_rows=negative, isolated_pipeorder=pipe, protocol_only_tcl=tcl)
(DOC / "coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
for row in batches:
    print(f"| {row['name']} | {row['passed']} | {row['failed']} |")
