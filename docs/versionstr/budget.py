#!/usr/bin/env python3
"""Reproduce main.cc-only inlining-budget trials; compile/inspect, never boot."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from versionstr_artifacts import reason
from ccfix4_budget import inventory, compare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("values", nargs="+", type=int)
    parser.add_argument("--db0", action="store_true")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--tag", default="budgets")
    args = parser.parse_args()
    relative = ("db0/" if args.db0 else "") + "src/main.o"
    output = ROOT / "build/versionstr" / args.tag / ("db0" if args.db0 else "multi")
    output.mkdir(parents=True, exist_ok=True)

    def selected(path):
        rows = inventory(path)
        for row in rows.values():
            row["hot"] = reason(relative, row["name"]) is None
        return rows

    old = selected(ROOT / "build/versionstr/PRE" / relative)

    def trial(value):
        target = output / (str(value) + ".o")
        cmd = ["taskset", "-c", "96-111", "g++", "-std=c++20", "-O2", "-g",
               "-Wall", "-Wextra", "-march=native", "-pthread", "-DTOMO_JEMALLOC", "-I.", "-fdump-ipa-inline-details=" + str(target.with_suffix(".inline")),
               "--param", "inline-unit-growth=0", "--param", "large-unit-insns=" + str(value)]
        cmd += (["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"] if args.db0 else ["-DTOMO_DUAL_DATABASE"])
        cmd += ["-c", "src/main.cc", "-o", str(target)]
        with target.with_suffix(".log").open("w") as log:
            subprocess.run(cmd, cwd=args.source_root, stdout=log, stderr=subprocess.STDOUT, check=True)
        result = {"command": cmd, "value": value, **compare(old, selected(target))}
        target.with_suffix(".json").write_text(json.dumps(result, indent=2) + "\n")
        print(value, result["hot_changed"], result["hot_differing_bytes"], flush=True)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(trial, args.values))


if __name__ == "__main__":
    main()
