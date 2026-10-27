#!/usr/bin/env python3
"""Validate finished proof receipts and write one reviewable coverage index."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs/protofix"
os.sched_setaffinity(0, set(range(16)))
read = lambda path: json.loads(path.read_text())
matrix, results = read(DOC / "matrix.json"), read(DOC / "matrix-results.json")
assert [row["name"] for row in results] == [row["name"] for row in matrix["batches"]]
assert all(row["exit"] == 0 for row in results), results
supplement = read(DOC / "supplement-results.json")
assert len(supplement) == 3 and all(row["exit"] == 0 for row in supplement), supplement
finish = read(DOC / "finish-results.json")
assert len(finish) == 5
assert all(row["exit"] == (1 if row["name"] == "pad-control" else 0) for row in finish), finish
post = hashlib.sha256((ROOT / "build/tomokv").read_bytes()).hexdigest()
assert post == matrix["post_sha256"]
names = [row["name"] for row in results] + [row["name"] for row in supplement[:2]]
batches = []
for name in names:
    receipt = read(DOC / "jobs" / (name + ".json"))
    assert receipt["exit"] == 0 and receipt["binary_unchanged"] and receipt["binary_sha256"] == post
    counts = re.search(r"GATE\(PARTIAL\): (\d+) ok, (\d+) FAIL", receipt["summary"][0])
    assert counts and counts[2] == "0", receipt
    batches.append(dict(name=name, passed=int(counts[1]), failed=int(counts[2]), seconds=receipt["seconds"],
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
pad = read(DOC / "jobs/verified-pad-control.json")
assert pad["binary_unchanged"] and pad["exit"] == 1
ledger = (DOC / "jobs/verified-pad-control.tsv.partial").read_text().splitlines()
negative = [line for line in ledger if line.startswith("FAIL\t")]
assert len(negative) == 4 and all("inline quoted argument decoding" in line for line in negative)
for mode, engine in itertools.product(("1s", "2s"), ("epoll", "uring")):
    text = (Path(pad["artifacts"]) / "jobs/inline_quoted" / (mode + "-" + engine + ".log")).read_text()
    assert "inline decoding: 7 cases, 7 failures" in text
gate_test = (ROOT / "build/protofix/gate-selftests-verified.log").read_text()
assert re.search(r"Ran 73 tests", gate_test) and re.search(r"^OK$", gate_test, re.M), gate_test[-2000:]
summary = dict(post_sha256=post, batches=batches, oracle=oracle,
               command_scope_exact_pairs=len(counts), hot_groups_equal=identity["hot_groups"],
               build_freshness_checks=len(build["freshness"]), gate_selftests=73,
               pad_expected_failed_rows=negative, isolated_pipeorder=pipe, protocol_only_tcl=tcl)
(DOC / "coverage.json").write_text(json.dumps(summary, indent=2) + "\n")
for row in batches:
    print(f"| {row['name']} | {row['passed']} | {row['failed']} |")
