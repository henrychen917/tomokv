#!/usr/bin/env python3
"""Whole additional protocol, read-local, reply-order and listener jobs."""
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
jobs = """reorder_sync reorder_engagement reorder_identity filter_unit ring_unit
wb_rule_units wbland_units wb_policy atomic_units bugs5 acl_recheck auth authfix
serverfix_hello dispatch_arity dispatch_errors dispatch_children acl_subcommands
router_uniform flip fliplisten ntnew4_live clientfix climonfix""".split()
matrix = [dict(name="verified-supplement-uring", jobs=jobs, engine="uring"),
          dict(name="verified-supplement-epoll",
               jobs="acl_recheck auth flip".split(), engine="epoll")]
results = []
for row in matrix:
    cmd = ["python3", "docs/protofix/run_jobs.py", row["name"], *row["jobs"], "--engine", row["engine"]]
    result = subprocess.run(cmd, cwd=ROOT)
    results.append(dict(**row, exit=result.returncode))
    (ROOT / "docs/protofix/supplement-results.json").write_text(json.dumps(results, indent=2) + "\n")
raise SystemExit(any(row["exit"] for row in results))
