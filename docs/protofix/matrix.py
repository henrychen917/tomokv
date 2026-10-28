#!/usr/bin/env python3
"""Declared protocol/network/read-local/pipeline jobs, serialized on lane CPUs."""
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
sha = hashlib.sha256((ROOT / "build/tomokv").read_bytes()).hexdigest()
protocol = """inline_quoted respcompat netio-1s netio-2s netcap netfix_query_stats
netfix_unix netfix_config netfix_tls netfix_idle_buffers ntfix_input iofix-deferred
iofix-hz iofix-sleep iofix-signal perfio_stream rlfix3_info rlfix3_zc readonly replyoff
tls zc rlcache netcmd_units splitlocal_units core_units bplus source_identity""".split()
protocol += [f"respresume-{kind}-{mode}-{engine}" for kind in ("fragment", "cpu", "neighbour")
             for mode in ("1s", "2s") for engine in ("epoll", "uring")]
features = """feature-split-0 feature-split-1 feature-armed-0 feature-armed-1
fused-0 fused-1 release_batteries asan_batteries atomic_batteries debug-0 debug-1""".split()
cells = ["feature-cell-" + "-".join(parts) for parts in itertools.product(("1s", "2s"), *[("0", "1")] * 4)]
cells += ["feature-cell-split-home-min", "feature-cell-fused-home-max-nopin", "feature-cell-split-shards-auto"]
matrix = [dict(name="verified-protocol-uring", jobs=protocol, engine="uring"),
          dict(name="verified-protocol-epoll", jobs="respcompat readonly replyoff tls zc rlcache bplus".split(), engine="epoll"),
          dict(name="verified-feature-cells", jobs=cells, engine="uring")]
for engine in ("uring", "epoll"):
    matrix += [dict(name="verified-features-" + engine, jobs=features, engine=engine),
               dict(name="verified-fused-" + engine,
                    jobs="release_batteries asan_batteries atomic_batteries debug-0 debug-1".split(), engine=engine, fused=True),
               dict(name="verified-differ-" + engine, jobs=["differ-split", "differ-armed"], engine=engine)]
out = ROOT / "docs/protofix"
(out / "matrix.json").write_text(json.dumps(dict(post_sha256=sha, batches=matrix), indent=2) + "\n")
results = []
for row in matrix:
    assert hashlib.sha256((ROOT / "build/tomokv").read_bytes()).hexdigest() == sha, "frozen binary changed"
    cmd = ["python3", "docs/protofix/run_jobs.py", row["name"], *row["jobs"], "--engine", row["engine"]]
    if row.get("fused"):
        cmd += ["--fused"]
    result = subprocess.run(cmd, cwd=ROOT)
    results.append(dict(name=row["name"], exit=result.returncode))
    (out / "matrix-results.json").write_text(json.dumps(results, indent=2) + "\n")
raise SystemExit(any(row["exit"] for row in results))
