#!/usr/bin/env python3
"""Compile-only GCC budget derivation; compare every unrelated function body."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
from respcompat_audit import audit

PRE = ROOT / "build/protofix/pre-source"
OUT = ROOT / "build/protofix/budgets"
DOC = ROOT / "docs/protofix/budgets"
OUT.mkdir(parents=True, exist_ok=True)
DOC.mkdir(parents=True, exist_ok=True)
OBJECTS = [prefix + name + ".o" for prefix in ("src/", "db0/src/")
           for name in ("main", "core/genthread", "core/reorder", "core/rl2s", "core/fliplisten")]
BUDGETS = {m[1]: int(m[2]) for m in re.finditer(
    r'^\$\(BUILD_ROOT\)/([^:\n]+):[^\n]*large-unit-insns=(\d+)', (PRE / "Makefile").read_text(), re.M)}


def compile_one(job):
    arm, obj, budget = job
    base = PRE if arm == "pre" else ROOT
    tag = (obj + "-" + arm + "-" + str(budget)).replace("/", "_")
    receipt = DOC / (tag + ".json")
    if receipt.exists():
        return json.loads(receipt.read_text())
    recipe = subprocess.check_output(["make", "-B", "-n", "build/" + obj], cwd=base, text=True)
    cmd = shlex.split(next(line for line in reversed(recipe.splitlines())
                          if line.startswith("g++ ") and line.endswith(" -o build/" + obj)))
    cmd = ["-g0" if x == "-g" else x for x in cmd]
    if budget is not None:
        cmd = ["large-unit-insns=" + str(budget) if x.startswith("large-unit-insns=") else x for x in cmd]
        if obj not in BUDGETS:
            cmd += ["--param", "inline-unit-growth=0", "--param", "large-unit-insns=" + str(budget)]
    dest = OUT / (tag + ".o")
    cmd[cmd.index("-o") + 1] = str(dest)
    cmd += ["-fdump-ipa-inline", "-dumpbase", str(OUT / tag)]
    with (OUT / (tag + ".log")).open("w") as log:
        subprocess.run(cmd, cwd=base, stdout=log, stderr=subprocess.STDOUT, check=True)
    dump, = OUT.glob(tag + "*.inline")
    with dump.open() as stream:
        unit = next(int(m[1]) for line in stream if (m := re.search(r"Starting with size (\d+)", line)))
    dump.unlink()
    old, new = audit.Elf(PRE / "build" / obj), audit.Elf(dest)
    fs, gs = old.functions(), new.functions()
    symbols = sorted(fs.keys() | gs.keys())
    labels = subprocess.check_output(["c++filt"], input="\n".join(symbols) + "\n", text=True).splitlines()
    changes = []
    for symbol, label in zip(symbols, labels):
        if re.search(r"resp_inline|resp_parse_inline|RespInlineDecoder", label):
            continue
        a, b = fs.get(symbol), gs.get(symbol)
        if not a or not b or old.canonical(a) != new.canonical(b):
            changes.append(dict(name=label, pre_size=a["size"] if a else 0, post_size=b["size"] if b else 0,
                                hot=bool(audit.HOT.search(label))))
    row = dict(arm=arm, object=obj, budget=budget, unit=unit, command=cmd,
               output=str(dest), changes=changes, hot_changes=sum(r["hot"] for r in changes))
    receipt.write_text(json.dumps(row, indent=2) + "\n")
    print(tag, unit, len(changes), row["hot_changes"], flush=True)
    return row


if __name__ == "__main__":
    phase = sys.argv[1]
    if phase == "initial":
        jobs = [(arm, obj, BUDGETS.get(obj)) for arm in ("pre", "post") for obj in OBJECTS]
    elif phase == "derived":
        rows = json.loads((DOC / "initial.json").read_text())
        by = {(r["arm"], r["object"]): r for r in rows}
        jobs = [("post", obj, budget + by["post", obj]["unit"] - by["pre", obj]["unit"])
                for obj, budget in BUDGETS.items() if obj in OBJECTS]
    elif phase in ("scan", "flip"):
        rows = json.loads((DOC / "initial.json").read_text())
        by = {(r["arm"], r["object"]): r for r in rows}
        jobs = []
        for obj in OBJECTS:
            if "genthread" in obj and phase == "scan":
                jobs.extend(("post", obj, BUDGETS[obj] + delta) for delta in range(-32, 137, 8))
            elif "fliplisten" in obj:
                growth = 1.4 if phase == "flip" else 1.3
                center = int(by["pre", obj]["unit"] * growth)
                jobs.extend(("post", obj, center + delta) for delta in range(-96, 193, 16))
    else:
        raise ValueError(phase)
    with ThreadPoolExecutor(16) as pool:
        rows = list(pool.map(compile_one, jobs))
    (DOC / (phase + ".json")).write_text(json.dumps(rows, indent=2) + "\n")
