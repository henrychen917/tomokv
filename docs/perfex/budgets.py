#!/usr/bin/env python3
"""Compile-only search for PRE identity outside the intended executor bodies."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from ccfix_audit import audit

EXPECTED = re.compile(r'ExLoopT<.*>::(?:drain_tasks|drain_tasks_read_local_interleaved|run\(|'
                      r'owner_control_tail|(?:r7_)?(?:fused_.*|sweep))')


def inventory(path):
    elf = audit.Elf(path)
    functions = elf.functions()
    names = sorted(functions)
    readable = subprocess.check_output(["c++filt"], input="\n".join(names) + "\n", text=True).splitlines()
    return {symbol: dict(name=name, canonical=elf.canonical(functions[symbol]), size=functions[symbol]["size"])
            for symbol, name in zip(names, readable) if audit.HOT.search(name) and not EXPECTED.search(name)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("object", help="e.g. src/core/genthread.o or db0/src/core/rl2s.o")
    p.add_argument("values", type=int, nargs="+")
    p.add_argument("--jobs", type=int, default=4)
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(112, 128))
    relative = Path(a.object)
    assert not relative.is_absolute() and ".." not in relative.parts
    pre = ROOT / "build/perfex/pre" / relative
    old = inventory(pre)
    assert old
    dry = subprocess.check_output(["make", "-n", "-B", str(Path("build") / relative)], cwd=ROOT, text=True)
    compile_lines = [shlex.split(line) for line in dry.splitlines()
                     if line.startswith("g++ ") and " -o " + str(Path("build") / relative) in line]
    assert len(compile_lines) == 1
    original = compile_lines[0]
    folder = ROOT / "build/perfex/budgets" / str(relative).replace("/", "-")
    folder.mkdir(parents=True, exist_ok=True)
    source_sha = hashlib.sha256((ROOT / "src/core/ex_loop.h").read_bytes()).hexdigest()

    def trial(value):
        target = folder / f"{value}.o"
        command = [f"large-unit-insns={value}" if token.startswith("large-unit-insns=")
                   else "-g0" if token == "-g" else token for token in original]
        assert any(token.startswith("large-unit-insns=") for token in command)
        command[command.index("-o") + 1] = str(target)
        with (folder / f"{value}.log").open("w") as log:
            subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
        new = inventory(target)
        changed = []
        for name in sorted(old.keys() | new.keys()):
            before, after = old.get(name), new.get(name)
            if before and after and before["canonical"] == after["canonical"]:
                continue
            changed.append(dict(symbol=name, name=(before or after)["name"],
                                pre_size=before["size"] if before else 0,
                                post_size=after["size"] if after else 0))
        result = dict(value=value, object=str(relative), source_sha256=source_sha, command=command,
                      checked=len(old.keys() | new.keys()), changed=changed)
        (folder / f"{value}.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(dict(object=str(relative), value=value, changed=len(changed),
                              bodies=[row["name"] for row in changed])), flush=True)
        return result

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = list(pool.map(trial, a.values))
    print("BEST", min(results, key=lambda row: len(row["changed"]))["value"], flush=True)


if __name__ == "__main__":
    main()
