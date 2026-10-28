#!/usr/bin/env python3
"""Whole additional protocol, read-local, reply-order and listener jobs."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
jobs = """reorder_sync reorder_engagement reorder_identity filter_unit ring_unit
wb_rule_units wbland_units wb_policy atomic_units exbatch_units exbatch_live perfex_units perfex_live bugs5 acl_recheck auth authfix
serverfix_hello dispatch_arity dispatch_errors dispatch_children acl_subcommands
router_uniform flip fliplisten ntnew4_live clientfix climonfix""".split()
matrix = [dict(name="verified-debug1-fused-uring-pre", jobs=["debug-1"], engine="uring", fused=True,
               binary="build/tomokv-protofix-PRE"),
          dict(name="verified-debug1-fused-uring-repeat", jobs=["debug-1"], engine="uring", fused=True),
          dict(name="verified-supplement-uring", jobs=jobs, engine="uring"),
          dict(name="verified-supplement-epoll",
               jobs="acl_recheck auth flip exbatch_live perfex_live".split(), engine="epoll")]
results = []
diagnostic = subprocess.run(["python3", "docs/protofix/wound_diagnostic.py"], cwd=ROOT)
(ROOT / "docs/protofix/wound-status.json").write_text(json.dumps(
    dict(diagnostic_exit=diagnostic.returncode), indent=2) + "\n")
for row in matrix:
    cmd = ["python3", "docs/protofix/run_jobs.py", row["name"], *row["jobs"], "--engine", row["engine"]]
    if row.get("fused"):
        cmd += ["--fused"]
    if row.get("binary"):
        cmd += ["--binary", row["binary"]]
    result = subprocess.run(cmd, cwd=ROOT)
    results.append(dict(**row, exit=result.returncode))
    (ROOT / "docs/protofix/supplement-results.json").write_text(json.dumps(results, indent=2) + "\n")
result = subprocess.run(["python3", "docs/protofix/tcl_protocol.py"], cwd=ROOT)
results.append(dict(name="protocol-only-tcl-diagnostic", exit=result.returncode))
(ROOT / "docs/protofix/supplement-results.json").write_text(json.dumps(results, indent=2) + "\n")
raise SystemExit(diagnostic.returncode != 0 or any(row["exit"] for row in results))
