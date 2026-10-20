#!/usr/bin/env python3
"""Compile-only ntfix3 inlining trials; fixed CPUs 80-95, up to 16 compiles.

Input is a JSON list of {object, budget?, tree?: "pre"|"post"}.
The compiler command is the production Makefile command captured by ntfix PRE.
Only large-unit-insns is varied; all bodies are compared with PRE 567d3b8e3.
"""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import ccfix_audit

audit = ccfix_audit.audit
LANE = re.compile(r"IoLoop::epoll_recv|WbEngine::pump_tls|parse_and_dispatch<|"
                  r"IoLoop::drive_tls<|IoLoop::arm_recv<|IoLoop::on_cqe|"
                  r"Client::read_space|Client::query_buffer")


def compare(path, obj):
    a, b = audit.Elf(ROOT / "build/ntfix-pre" / obj), audit.Elf(path)
    old, new = a.functions(), b.functions()
    symbols = sorted(old.keys() | new.keys())
    names = subprocess.check_output(
        ["taskset", "-c", "80-95", "c++filt"],
        input="\n".join(symbols) + "\n", text=True).splitlines()
    changes = []
    for symbol, name in zip(symbols, names):
        x, y = old.get(symbol), new.get(symbol)
        if x and y and a.canonical(x) == b.canonical(y):
            continue
        kind = ("lane" if LANE.search(name) else
                "hot" if audit.HOT.search(name) or re.search(r"ExLoopT<.*>::run\(", name)
                else "other")
        changes.append(dict(kind=kind, name=name,
                            pre=x["size"] if x else 0, post=y["size"] if y else 0))
    return changes


def trial(job, source_keys, outdir):
    obj, tree = job["object"], job.get("tree", "post")
    root = ROOT if tree == "post" else ROOT / "build/pre-src"
    lines = (ROOT / "docs/ntfix/pre/build.log").read_text().splitlines()
    command = next(shlex.split(line) for line in lines
                   if line.startswith("g++ ") and line.endswith(" -o build/" + obj))
    if "budget" in job:
        for i, arg in enumerate(command):
            if arg.startswith("large-unit-insns="):
                command[i] = "large-unit-insns=" + str(job["budget"])
                break
        else:
            command += ["--param", "inline-unit-growth=0",
                        "--param", "large-unit-insns=" + str(job["budget"])]
    key = hashlib.sha256((str(root) + source_keys[tree] +
                          " ".join(command)).encode()).hexdigest()[:16]
    base = ROOT / "build/ntfix3/trials" / (obj.replace("/", "_") + "." + key)
    base.parent.mkdir(parents=True, exist_ok=True)
    output = base.with_suffix(base.suffix + ".o")
    receipt = base.with_suffix(base.suffix + ".json")
    command[command.index("-o") + 1] = str(output)
    command += ["-fdump-ipa-inline", "-dumpbase", str(base)]
    if receipt.exists():
        row = json.loads(receipt.read_text())
    else:
        with base.with_suffix(base.suffix + ".log").open("w") as log:
            subprocess.run(["taskset", "-c", "80-95", *command], cwd=root,
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        dump = next(base.parent.glob(base.name + "*.inline"))
        with dump.open(errors="replace") as stream:
            unit = next(int(m[1]) for line in stream
                        if (m := re.search(r"Starting with size (\d+)", line)))
        dump.unlink()
        changes = compare(output, obj)
        row = dict(job, tree=tree, source_sha256=source_keys[tree], unit=unit,
                   command=command, output=str(output),
                   sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                   counts={k: sum(c["kind"] == k for c in changes)
                           for k in ("lane", "hot", "other")}, changes=changes)
        receipt.write_text(json.dumps(row, indent=2) + "\n")
    name = obj.replace("/", "_") + f".{tree}.{job.get('budget', 'default')}.json"
    (outdir / name).write_text(json.dumps(row, indent=2) + "\n")
    print(json.dumps({k: row[k] for k in ("object", "tree", "unit", "counts")} |
                     {"budget": job.get("budget")}), flush=True)
    return row


def main():
    jobs = json.loads(Path(sys.argv[1]).read_text())
    outdir = Path(sys.argv[2])
    outdir.mkdir(parents=True, exist_ok=True)
    keys = {}
    for tree in {j.get("tree", "post") for j in jobs}:
        root = ROOT if tree == "post" else ROOT / "build/pre-src"
        digest = hashlib.sha256()
        for path in sorted((root / "src").rglob("*")):
            if path.is_file():
                digest.update(str(path.relative_to(root)).encode() + path.read_bytes())
        keys[tree] = digest.hexdigest()
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(trial, j, keys, outdir) for j in jobs]
        rows = [f.result() for f in futures]
    (outdir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n")


if __name__ == "__main__":
    main()
