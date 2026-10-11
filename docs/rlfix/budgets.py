#!/usr/bin/env python3
"""Compile-only IPA budget trials with complete PRE body inventories."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ccfix4_budget import compare, inventory


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--objects", nargs="+", required=True)
    p.add_argument("--deltas", nargs="+", type=int, required=True)
    p.add_argument("--jobs", type=int, default=8)
    a = p.parse_args()
    baseline = {name: inventory(ROOT / "build/rlfix/pre" / name) for name in a.objects}
    commands = {}
    for name in a.objects:
        recipe = subprocess.check_output(["make", "-n", "-B", "build/" + name], text=True)
        commands[name] = shlex.split(next(line for line in recipe.splitlines() if line.startswith("g++ ")))
    digest = hashlib.sha256()
    for path in sorted((ROOT / "src").rglob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    tree = digest.hexdigest()
    def trial(pair):
        name, delta = pair
        command = commands[name].copy()
        index = next(i for i, token in enumerate(command) if token.startswith("large-unit-insns="))
        budget = int(command[index].split("=")[1]) + delta
        command[index] = f"large-unit-insns={budget}"
        folder = ROOT / "build/rlfix/budgets" / tree[:12] / name.replace("/", "_") / str(budget)
        folder.mkdir(parents=True, exist_ok=True)
        receipt = folder / "result.json"
        if receipt.exists():
            result = json.loads(receipt.read_text())
        else:
            command[command.index("-g")] = "-g0"
            command[command.index("-o") + 1] = str(folder / "unit.o")
            command += ["-fdump-ipa-inline"]
            command = ["taskset", "-c", "48-63"] + command
            with (folder / "compile.log").open("w") as log:
                subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
            result = dict(object=name, delta=delta, budget=budget, source_sha256=tree,
                          command=command, **compare(baseline[name], inventory(folder / "unit.o")))
            receipt.write_text(json.dumps(result, indent=2) + "\n")
        # The feature necessarily changes the armed parser and local resolver.
        # Preserve the complete list; do not hide these from the standard auditors.
        unexpected = [r for r in result["rows"] if not any(s in r["name"] for s in
                      ("parse_and_dispatch<true", "prepare_local_read", "drain_local_reads_bounded_impl",
                       "read_local_command_is_", "ReadLocalDemotionPlan::prepare"))]
        print(name, budget, "hot", result["hot_changed"], "all", result["changed"],
              "outside", len(unexpected), flush=True)
        result["outside"] = unexpected
        return result
    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        rows = list(pool.map(trial, [(name, d) for name in a.objects for d in a.deltas]))
    for name in a.objects:
        best = min((r for r in rows if r["object"] == name),
                   key=lambda r: (len(r["outside"]), r["hot_changed"], r["changed"]))
        print("BEST", name, best["budget"], len(best["outside"]), flush=True)


if __name__ == "__main__":
    main()
