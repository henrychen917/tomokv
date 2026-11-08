#!/usr/bin/env python3
"""Reproducible serverless command/EXEC counts, bound to each linked image."""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path

os.environ["EXEC1S_CPUS"] = "0-31"
import exec1s_scope as scope

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "build/execfifo2"

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arms", default="PRE,POST")
    p.add_argument("--kind", choices=("commands", "exec", "owner"), default="commands")
    p.add_argument("--build-only", action="store_true")
    p.add_argument("--trace-only", action="store_true")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--overrides", type=Path)
    p.add_argument("--tag", default="")
    p.add_argument("--commands", default="")
    args = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(32))
    arms = args.arms.split(",")
    scope.OUT = ROOT / "docs/execfifo2" / (args.kind + args.tag)
    scope.BUILD = BASE / (args.kind + args.tag + "-scopes")
    scope.OUT.mkdir(parents=True, exist_ok=True)
    scope.BUILD.mkdir(parents=True, exist_ok=True)
    scope.ARMS = {"PRE": (BASE / "pre-source", BASE / "pre-source/build"),
                  "B": (BASE / "B-source", BASE / "B-source/build"),
                  "POST": (ROOT, ROOT / "build")}
    scope.SYMBOL_PREFIXES = {}
    if args.overrides:
        assert arms == ["POST"], "compile-only override is a POST diagnostic"
        scope.OBJECT_OVERRIDES = json.loads(args.overrides.read_text())
    if args.kind == "exec":
        scope.FIXTURE = ROOT / "tests/exec1sd_scope.cc"
    if args.kind == "owner":
        scope.FIXTURE = ROOT / "tests/execfifo2_owner_scope.cc"
    if not args.trace_only:
        for arm in arms:
            for ns in ("normal", "db0"):
                scope.build(arm, ns)
    if args.build_only:
        return
    if args.kind == "commands":
        cases = [(arm, ns, cmd, mode, batch, atomic, -1)
                 for arm in arms for ns in ("normal", "db0")
                 for cmd in ("GET", "SET", "INCR", "MGET", "MSET")
                 for mode in ("1s", "2s") for batch in (1, 32)
                 for atomic in ((0, 1) if cmd == "MSET" else (1,))]
    else:
        cases = [(arm, ns, cmd, mode, children, atomic, -1)
                 for arm in arms for ns in ("normal", "db0")
                 for cmd in (("OWNER-single", "OWNER-cross") if args.kind=="owner" else ("EXEC", "EXEC-cross")) for mode in ("1s", "2s")
                 for children in (1, 2, 4) for atomic in (0, 1)]
    if args.commands:
        cases = [c for c in cases if c[2] in args.commands.split(",")]
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        rows = list(pool.map(scope.trace, cases))
    scope.save(scope.OUT / ("results-" + args.arms + ".json"), rows)
    keys = ("namespace", "command", "mode", "batch", "atomic", "threshold")
    pairs = []
    if "PRE" in arms:
        for row in rows:
            if row["arm"] == "PRE": continue
            old = next(r for r in rows if r["arm"] == "PRE" and all(r[k] == row[k] for k in keys))
            functions = sorted(set(old["functions"]) | set(row["functions"]))
            pairs.append({k: row[k] for k in keys} | dict(arm=row["arm"], pre=old["total"],
                post=row["total"], delta=row["total"]-old["total"],
                functions={f: row["functions"].get(f,0)-old["functions"].get(f,0)
                           for f in functions if row["functions"].get(f,0)!=old["functions"].get(f,0)}))
        scope.save(scope.OUT / "comparison.json", pairs)
        if args.kind == "commands" and pairs:
            assert all(row["delta"] <= 0 for row in pairs), "added command-scope instructions"

if __name__ == "__main__": main()
