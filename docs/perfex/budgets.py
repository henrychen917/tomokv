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
from threading import Event

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
    p.add_argument("--max-auto", type=int, help="optional max-inline-insns-auto trial")
    p.add_argument("--source-root", type=Path, default=ROOT)
    p.add_argument("--tag", help="separate an isolated source experiment's objects")
    p.add_argument("--stop-on-match", action="store_true", help="stop starting trials after a byte match")
    a = p.parse_args()
    assert os.sched_getaffinity(0) <= set(range(112, 128))
    source = a.source_root.resolve()
    assert source.is_relative_to(ROOT)
    assert (source == ROOT) or a.tag, "isolated sources need a separate artifact tag"
    relative = Path(a.object)
    assert not relative.is_absolute() and ".." not in relative.parts
    pre = ROOT / "build/perfex/pre" / relative
    old = inventory(pre)
    assert old
    dry = subprocess.check_output(["make", "-n", "-B", str(Path("build") / relative)], cwd=source, text=True)
    compile_lines = [shlex.split(line) for line in dry.splitlines()
                     if line.startswith("g++ ") and " -o " + str(Path("build") / relative) in line]
    assert len(compile_lines) == 1
    original = compile_lines[0]
    folder = ROOT / "build/perfex/budgets" / str(relative).replace("/", "-")
    if a.tag:
        assert re.fullmatch(r"[a-z0-9-]+", a.tag)
        folder = folder / a.tag
    if a.max_auto is not None:
        folder = folder / f"auto-{a.max_auto}"
    folder.mkdir(parents=True, exist_ok=True)
    source_sha = hashlib.sha256((source / "src/core/ex_loop.h").read_bytes()).hexdigest()
    matched = Event()

    def trial(value):
        if a.stop_on_match and matched.is_set():
            return None
        target = folder / f"{value}.o"
        command = [f"large-unit-insns={value}" if token.startswith("large-unit-insns=")
                   else "-g0" if token == "-g" else token for token in original]
        assert any(token.startswith("large-unit-insns=") for token in command)
        if a.max_auto is not None:
            command += ["--param", f"max-inline-insns-auto={a.max_auto}"]
        command[command.index("-o") + 1] = str(target)
        with (folder / f"{value}.log").open("w") as log:
            subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT, check=True)
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
        if not changed:
            matched.set()
        return result

    with ThreadPoolExecutor(max_workers=a.jobs) as pool:
        results = [result for result in pool.map(trial, a.values) if result is not None]
    print("BEST", min(results, key=lambda row: len(row["changed"]))["value"], flush=True)


if __name__ == "__main__":
    main()
