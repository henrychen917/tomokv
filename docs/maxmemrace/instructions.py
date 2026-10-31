#!/usr/bin/env python3
"""Lane maxmemrace: link the bounded serverless command fixture against each arm, no rates.

Derived from docs/pubtrackfix/instructions.py. tests/wave9_scope.cc calls the linked
production entry points (owner exec_batch_prefetched, xshard_prepare/execute/complete/
retire, local parse/drain) in both namespaces. PRE objects come from an exported
e32b04a44 tree built under build/maxmemrace/pre-tree; POST objects from build/.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/maxmemrace/instructions"
BUILD = ROOT / "build/maxmemrace/counts"
PRE_TREE = ROOT / "build/maxmemrace/pre-tree"
PRE_COMMIT = "e32b04a44"
ARMS = {"pre": (PRE_TREE, PRE_TREE), "post": (ROOT, ROOT / "build")}


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def export_pre():
    """git archive of PRE sources, built in place (BUILD_ROOT = the tree itself)."""
    if not (PRE_TREE / "Makefile").exists():
        PRE_TREE.mkdir(parents=True, exist_ok=True)
        archive = subprocess.check_output(
            ["git", "archive", PRE_COMMIT, "src", "third_party", "Makefile", "tools/assert_map.py"],
            cwd=ROOT)
        with tarfile.open(fileobj=io.BytesIO(archive)) as t:
            t.extractall(PRE_TREE, filter="data")
    with (BUILD / "pre-tree-build.log").open("w") as log:
        subprocess.run(["taskset", "-c", "32-47", "make", "-j16", "BUILD_ROOT=" + str(PRE_TREE), "all"],
                       cwd=PRE_TREE, stdout=log, stderr=subprocess.STDOUT, check=True)


def build(arm, ns):
    source, objects = ARMS[arm]
    dest = BUILD / (arm + "-" + ns)
    dest.mkdir(parents=True, exist_ok=True)
    recipe = subprocess.check_output(["make", "-C", str(source), "BUILD_ROOT=" + str(objects),
                                     "-n", "-W", str(objects / "src/main.o"), "all"], text=True)
    link = shlex.split(next(line for line in recipe.splitlines()
                            if " -o " + str(objects / "tomokv") + " " in line))
    flags = ["g++", "-std=c++20", "-O2", "-g", "-march=native", "-pthread", "-DTOMO_JEMALLOC",
             "-I" + str(source)]
    if ns == "db0":
        flags += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
    compile_cmd = flags + ["-c", str(ROOT / "tests/wave9_scope.cc"), "-o", str(dest / "probe.o")]
    renamed_main = dest / "original-main.o"
    rename_cmd = ["objcopy", "--redefine-sym", "main=execfair_original_main",
                  str(objects / "db0/src/main.o"), str(renamed_main)]
    link = [str(renamed_main) if arg == str(objects / "db0/src/main.o") else arg for arg in link]
    link += [str(dest / "probe.o")]
    link[link.index("-o") + 1] = str(dest / "probe")
    with (OUT / (arm + "-" + ns + "-build.log")).open("w") as log:
        for cmd in (compile_cmd, rename_cmd, link):
            subprocess.run(["taskset", "-c", "32-47", *cmd], stdout=log, stderr=subprocess.STDOUT,
                           check=True)
    save(OUT / (arm + "-" + ns + "-build.json"),
         {"compile": compile_cmd, "rename": rename_cmd, "link": link,
          "sha256": hashlib.sha256((dest / "probe").read_bytes()).hexdigest()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--arms', default='pre,post')
    parser.add_argument('--skip-pre-tree', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    arms = args.arms.split(',')
    if 'pre' in arms and not args.skip_pre_tree:
        export_pre()
    for arm in arms:
        for ns in ('normal', 'db0'):
            build(arm, ns)


if __name__ == '__main__':
    main()
