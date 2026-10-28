#!/usr/bin/env python3
"""Bounded serverless paths in linked production routines, no rates.

Derived from docs/wave6/commands.py, using the wave7 production scope.
Count named tomo routines (including inlined code), exclude out-of-scope library
callees and fixture glue. The fixture calls the linked production exec_batch_prefetched entry point. Atomic 1 (also 0 for MSET), slowlog -1/10000 for single-key commands, read-local 0.
"""
import argparse
import concurrent.futures
import gzip
import hashlib
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/climonfix4/instructions"
BUILD = ROOT / "build/climonfix4/commands"
OUT.mkdir(parents=True,exist_ok=True)
BUILD.mkdir(parents=True,exist_ok=True)
ARMS = {"pre": (ROOT/"build/climonfix4/pre-source", ROOT/"build/climonfix4/pre-source/build"),
        "post": (ROOT, ROOT/"build")}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def build(arm, ns):
    source, objects = ARMS[arm]
    dest = BUILD / (arm + "-" + ns)
    dest.mkdir(exist_ok=True)
    recipe = subprocess.check_output(["make", "-C", str(source), "BUILD_ROOT=" + str(objects),
                                     "-n", "-W", str(objects / "src/main.o"), "all"], text=True)
    link = shlex.split(next(line for line in recipe.splitlines() if " -o " + str(objects / "tomokv") + " " in line))
    flags = ["g++", "-std=c++20", "-O2", "-g", "-march=native", "-pthread", "-DTOMO_JEMALLOC", "-I" + str(source)]
    if ns == "db0":
        flags += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
    compile_cmd = flags + ["-c", str(ROOT / "tests/wave9_scope.cc"), "-o", str(dest / "probe.o")]
    # main.o supplies the actual split executor instantiation. Keep both main
    # objects in their production link order and rename only the program entry.
    # Put fixture COMDATs last so production definitions keep precedence.
    renamed_main = dest / "original-main.o"
    rename_cmd = ["objcopy", "--redefine-sym", "main=execfair_original_main",
                  str(objects / "db0/src/main.o"), str(renamed_main)]
    link = [str(renamed_main) if arg == str(objects / "db0/src/main.o") else arg
            for arg in link]
    link += [str(dest / "probe.o")]
    link[link.index("-o") + 1] = str(dest / "probe")
    with (OUT / (arm + "-" + ns + "-build.log")).open("w") as log:
        subprocess.run(compile_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(rename_cmd, stdout=log, stderr=subprocess.STDOUT, check=True)
        subprocess.run(link, stdout=log, stderr=subprocess.STDOUT, check=True)
    save(OUT / (arm + "-" + ns + "-build.json"), {"compile": compile_cmd, "rename": rename_cmd, "link": link,
         "sha256": hashlib.sha256((dest / "probe").read_bytes()).hexdigest()})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--arms',default='pre,post')
    args=parser.parse_args()
    for arm in args.arms.split(','):
        for ns in ('normal','db0'): build(arm,ns)

if __name__ == '__main__': main()
