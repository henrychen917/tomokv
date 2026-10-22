#!/usr/bin/env python3
"""Compile the identical D2 fixture against the frozen PRE sources/objects."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import subprocess
pre = Path("build/moverfix/pre")

def build(db0):
    tag = "db0/src" if db0 else "src"
    objs = sorted(str(p) for p in (pre / tag).rglob("*.o")
                  if p.relative_to(pre / tag).as_posix() not in ("main.o", "cmd/xshard.o", "core/version.o"))
    if db0:
        objs += sorted(str(p) for p in (pre / "src").rglob("*.o")
                       if p.relative_to(pre / "src").as_posix() not in ("main.o", "core/version.o"))
    target = pre / ("moverfix-db0-unit" if db0 else "moverfix-unit")
    cmd = ["g++", "-std=c++20", "-O2", "-g", "-Wall", "-Wextra", "-march=native", "-pthread", "-DTOMO_JEMALLOC"]
    if db0:
        cmd += ["-DTOMO_SINGLE_DATABASE=1", "-Dtomo=tomo_db0"]
    cmd += ["-Ibuild/moverfix/pre-source", "tests/moverfix_unit.cc", *objs, "-o", str(target),
            "-ljemalloc", "-luring", "-pthread", "-lssl", "-lcrypto", "-lm"]
    with Path("docs/moverfix/" + target.name + "-pre-final-build.log").open("w") as f:
        rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT).returncode
    return dict(command=cmd, rc=rc)
with ThreadPoolExecutor(2) as pool:
    rows = list(pool.map(build, (False, True)))
Path("docs/moverfix/pre-unit-builds.json").write_text(json.dumps(rows, indent=2) + "\n")
assert all(r["rc"] == 0 for r in rows)
