#!/usr/bin/env python3
"""Build the fix-removed unit/server controls; only --run-units executes proofs.

Never starts a server, load generator, gate, or measurement. Run from this
worktree under taskset -c 112-127 after make -j16 all build/multidb-unit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build/sortstore-controls"


def run(name, command, expected=0, assertion=None):
    result = subprocess.run(command, cwd=ROOT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (OUT / f"{name}.log").write_text(
        "$ " + shlex.join(command) + "\n" + result.stdout + f"\nSTATUS {result.returncode}\n")
    if result.returncode != expected or (assertion and assertion not in result.stdout):
        raise RuntimeError(f"{name}: status {result.returncode}; see {OUT / (name + '.log')}")
    print(f"{name}: status={result.returncode}", flush=True)
    return dict(name=name, command=command, status=result.returncode, assertion=assertion)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-units", action="store_true", help="mainline: run positive/negative units")
    args = parser.parse_args()
    if not os.sched_getaffinity(0) <= set(range(112, 128)):
        parser.error("pin this driver to cores 112-127")
    OUT.mkdir(parents=True, exist_ok=True)
    source = subprocess.check_output(
        ["git", "show", "b8fe404e2:src/cmd/cmdmeta.cc"], cwd=ROOT, text=True)
    fixed = (ROOT / "src/cmd/cmdmeta.cc").read_text()
    start = fixed.index("                // Redis 7.4 sortGetKeys skips option operands:")
    end = fixed.index('else if (ascii_equal_icase(op.arg(index), Slice("STORE", 5)))', start)
    removed = fixed[:start] + "                " + fixed[end:].replace("else if", "if", 1)
    if removed != source:
        raise RuntimeError("the negative control must remove only the SORT fix")
    negative = OUT / "cmdmeta-nofix.cc"
    negative.write_text(removed)
    dry = subprocess.check_output(["make", "-nB", "all", "build/multidb-unit"], cwd=ROOT, text=True)
    commands = [shlex.split(line) for line in dry.splitlines() if " -o " in line]

    def command_for(output):
        matches = [cmd for cmd in commands if "-o" in cmd and cmd[cmd.index("-o") + 1] == output]
        if len(matches) != 1:
            raise RuntimeError(f"expected one make recipe for {output}, got {len(matches)}")
        return matches[0]

    replacements = {}
    for directory, label in (("", "multi"), ("db0/", "db0")):
        original = f"build/{directory}src/cmd/cmdmeta.o"
        replacement = str(OUT / f"cmdmeta-{label}-nofix.o")
        replacements[original] = replacement
        command = [str(negative) if arg == "src/cmd/cmdmeta.cc" else
                   replacement if arg == original else arg for arg in command_for(original)]
        run(f"compile-{label}-nofix", command + ["-Isrc/cmd"])
    for original, negative_binary in (("build/tomokv", "build/tomokv-sortstore-nofix"),
                                      ("build/multidb-unit", "build/multidb-unit-sortstore-nofix")):
        replacement = {**replacements, original: negative_binary}
        run("link-" + Path(negative_binary).name,
            [replacement.get(arg, arg) for arg in command_for(original)])
    binaries = ("build/tomokv", "build/tomokv-sortstore-pre", "build/tomokv-sortstore-nofix",
                "build/multidb-unit", "build/multidb-unit-sortstore-nofix")
    manifest = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                for path in binaries if (ROOT / path).exists()}
    (OUT / "sha256.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.run_units:
        results = []
        for selection, failure in (
            ("oracle-keys", "FAIL sortstore: oracle: metadata/execution key indexes"),
            ("oracle-stamp", "FAIL sortstore: oracle: only actual keys stamped; LIMIT untouched"),
            ("battery", "FAIL sortstore: oracle: metadata/execution key indexes"),
        ):
            for arm, binary, status, assertion in (
                ("post", "build/multidb-unit", 0, f"PASS sortstore {selection}:"),
                ("nofix", "build/multidb-unit-sortstore-nofix", 1, failure),
            ):
                results.append(run(f"{arm}-{selection}", [binary, "--sortstore-check", selection],
                                   status, assertion))
        (OUT / "unit-results.json").write_text(json.dumps(results, indent=2) + "\n")
    else:
        print("Proof execution PENDING mainline; no assertion has been run.")


if __name__ == "__main__":
    main()
