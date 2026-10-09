#!/usr/bin/env python3
"""Invoke only the gate's core-TSAN build recipe; never dispatch gate jobs."""
import gzip
import json
import os
from pathlib import Path
import shlex
import subprocess

root = Path.cwd()
out = root / "build/versionstr4/core-tsan-job"
out.mkdir(parents=True, exist_ok=True)
(out / "unit-ready/core-concurrency-tsan").unlink(missing_ok=True)
gate = (root / "tests/gate.sh").read_text()
body = gate[gate.index("job_core_tsan_build(){"):gate.index("tsan_unit(){")]
script = """set -eu
pausable(){ "$@"; }
set -x
export SHELLOPTS
""" + body + "\njob_core_tsan_build\n"
env = dict(os.environ, BUILD_CORES="112-127", PARBUILD_JOBS="16", RUN_DIR=str(out),
           TMPDIR=str(out), CORE_TSAN=str(root / "build/versionstr4/core-concurrency-tsan"))
cmd = ["taskset", "-c", "112-127", "bash", "-c", script]
result = subprocess.run(cmd, env=env, capture_output=True, text=True)
log = result.stdout + result.stderr + (out / "build.log").read_text()
docs = root / "docs/versionstr/versionstr4"
(docs / "core-tsan-build.log.gz").write_bytes(gzip.compress(log.encode(), mtime=0))
ready = (out / "unit-ready/core-concurrency-tsan").is_file()
links = []
for line in log.splitlines():
    if line.startswith("+ g++ "):
        args = shlex.split(line[2:])
        if "-c" not in args:
            links.append(args)
assert result.returncode == 0 and ready, result.stderr
assert len(links) == 1, links
assert not any("version.o" in arg or "version.cc" in arg for arg in links[0]), links[0]
objects = [arg for arg in links[0] if arg.endswith(".o")]
assert len(objects) == 47 and "-fsanitize=thread" in links[0], links[0]
(docs / "core-tsan-build.json").write_text(json.dumps(dict(
    exit=result.returncode, ready=ready, affinity="112-127", jobs=16,
    recipe="tests/gate.sh:job_core_tsan_build", sources=len(objects), link=links[0]), indent=2) + "\n")
print("PASS: real core TSAN build, 47 instrumented inputs, no version object, ready marker published")
