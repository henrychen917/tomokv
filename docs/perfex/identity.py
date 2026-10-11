#!/usr/bin/env python3
"""Classify the unmodified byte checkers' complete inventory for this lane."""
import argparse
import gzip
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from lbstall_artifacts import HOT


def reason(row):
    name = row["name"]
    if "::Shard::publish_size()" in name:
        return "EX4.2: batch publication retains counts/field attention and drops monitoring probes"
    if "::FlatStore::publish_keyspace_sample()" in name:
        return "EX4.2: field attention moves to count publication; this method only samples TTLs"
    if "::ExLoopT<" in name:
        if "::drain_tasks" in name or "::exec_batch<" in name:
            return "EX4.13: construct received Task slots; the smaller drain also changes batch inlining"
        if "::run()" in name:
            return "EX4.12: sample CPU time on the diagnostic beat; refresh cached wall time after it"
        if "::keyspace_sample_cycle()" in name:
            return "EX4.2: new bounded owner sampler on the millisecond beat"
        if "::owner_control_tail()" in name or "::r7_fused_sweep_impl<" in name:
            return "EX4.2: owner beat calls the monitoring sampler (including inline copies)"
        if "::fused_pass_impl<" in name or "::r7_fused_pass_impl<" in name:
            return "EX4.2/13: fused executor pass calls owner maintenance and the changed drains; their inlining changes"
        if "::ExLoopT()" in name:
            return "EX4.2: initialize the owner cursor in existing padding"
    if name in ("main", "main.cold"):
        return "EX4.2: cursor construction/cleanup inlining in cold boot code"
    return None


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    args = p.parse_args()
    with gzip.open(args.directory / "full/bodies.json.gz", "rt") as stream:
        rows = json.load(stream)
    changed = [row for row in rows if not row["equal"]]
    other_hot = []
    for row in changed:
        intended = reason(row)
        row["requested_hot_selection"] = bool(HOT.search(row["name"]) or
            re.search(r"ExLoopT<.*>::run\(", row["name"]))
        if row["requested_hot_selection"] and intended is None:
            other_hot.append(row)
        row["reason"] = intended or (
            "Compiler inlining/register allocation changed in a modified translation unit; "
            "source body unedited, outside the requested hot selection")
        row["direct_finding_or_inline_caller"] = intended is not None
    handlers = [row for row in rows if re.search(r"::cmd_\w+(?:<|\()", row["name"])]
    table = {}
    for namespace, filename in (("tomo", "hot-tomo.json"), ("tomo_db0", "hot-db0.json")):
        stock = json.loads((args.directory / filename).read_text())
        table[namespace] = dict(total=len(stock), identical=sum(row["relocation_equal"] for row in stock),
                                changed=sum(not row["relocation_equal"] for row in stock))
    hot = [row for row in rows if HOT.search(row["name"]) or
           re.search(r"ExLoopT<.*>::run\(", row["name"])]
    result = dict(stock_hot=table, full_bodies=len(rows), full_identical=sum(row["equal"] for row in rows),
                  full_hot=len(hot), full_hot_identical=sum(row["equal"] for row in hot),
                  handlers=len(handlers), handlers_identical=sum(row["equal"] for row in handlers),
                  unrelated_requested_hot=other_hot,
                  outside_hot_selection_changes=sum(not row["requested_hot_selection"] and
                      not row["direct_finding_or_inline_caller"] for row in changed),
                  scope="Canonical opcodes and resolved relocation targets; nonselected changes remain listed")
    (args.directory / "identity.json").write_text(json.dumps(result, indent=2) + "\n")
    (args.directory / "changed-body-reasons.json").write_text(json.dumps(changed, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    assert not other_hot, "unrelated body in the requested hot selection changed"
    assert all(row["equal"] for row in handlers), "command handler changed"


if __name__ == "__main__":
    main()
