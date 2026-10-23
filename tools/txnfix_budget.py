#!/usr/bin/env python3
"""Compile and compare one object's hot bodies; never starts a workload."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess

from ccfix_audit import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("object", help="object relative to build/, including optional db0/")
    parser.add_argument("budgets", nargs="+", type=int)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--include", default="", help="also compare names matching this regex")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    obj = Path(args.object)
    source = str(obj).removeprefix("db0/").removesuffix(".o") + ".cc"
    pre = root / "build/txnfix2/pre" / obj
    out = root / "build/txnfix2/budgets" / str(obj).replace("/", "_")
    out.mkdir(parents=True, exist_ok=True)
    before = audit.Elf(pre)
    functions = before.functions()
    symbols = list(functions)
    names = subprocess.check_output(["c++filt"], input="\n".join(symbols), text=True).splitlines()
    selected = [(symbol, name) for symbol, name in zip(symbols, names)
                if audit.HOT.search(name) or "xshard_execute(" in name or
                (args.include and re.search(args.include, name))]
    canonical = {symbol: before.canonical(functions[symbol]) for symbol, _ in selected}
    recipe = subprocess.check_output(
        ["make", "--no-print-directory", "-n", "-W", source, "build/" + str(obj)],
        cwd=root, text=True).replace("\\\n", " ")
    command = shlex.split(next(line for line in recipe.splitlines()
                              if " -c " + source + " " in line))
    digest = hashlib.sha256()
    for path in [root / "Makefile", *sorted((root / "src").rglob("*"))]:
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            digest.update(path.read_bytes())
    identity = dict(source_sha256=digest.hexdigest(), object=str(obj),
                    pre_sha256=hashlib.sha256(pre.read_bytes()).hexdigest())

    def trial(budget):
        target = out / f"{budget}.o"
        cmd = command.copy()
        cmd[cmd.index("-o") + 1] = str(target)
        cmd += ["-g0", "--param", f"large-unit-insns={budget}"]
        cmd = ["taskset", "-c", "112-127", *cmd]
        with (out / f"{budget}.log").open("w") as log:
            subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        after = audit.Elf(target)
        new = after.functions()
        rows = [dict(name=name, symbol=symbol, pre_size=functions[symbol]["size"],
                     post_size=new[symbol]["size"] if symbol in new else 0,
                     equal=symbol in new and canonical[symbol] == after.canonical(new[symbol]))
                for symbol, name in selected]
        result = dict(**identity, budget=budget, command=cmd, rows=rows,
                      changed=sum(not r["equal"] for r in rows))
        (out / f"{budget}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(str(obj), budget, result["changed"], flush=True)
        return result

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(trial, args.budgets))


if __name__ == "__main__":
    main()
