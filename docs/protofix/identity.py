#!/usr/bin/env python3
"""Reproduce the strict linked audit, including every counted command function."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
os.sched_setaffinity(0, set(range(16)))
scope = runpy.run_path(str(ROOT / "docs/wave8/identity.py"), run_name="protofix_linked_audit")
scope["inventory"].__globals__["OUT"] = ROOT / "build/protofix/linked-identity"
scope["COUNTED_HOT"].update(scope["audit"].canonical(name)
    for row in json.loads((ROOT / "docs/protofix/instructions-final/results.json").read_text())
    for name in row["functions"])
paths = [ROOT / "build/protofix/pre-source/build/tomokv", ROOT / "build/tomokv"]
with ThreadPoolExecutor(2) as pool:
    pre, post = pool.map(scope["inventory"], paths)
rows = scope["compare"](post, {"headline": pre})
changed = [row for row in rows if not row["equal"]]
result = dict(pre_sha256=pre["sha256"], post_sha256=post["sha256"], groups=len(rows),
              changed=len(changed), hot_groups=sum(row["hot"] for row in rows),
              counted_command_groups=sum(row["counted_command_scope"] for row in rows),
              hot_changed=[row for row in changed if row["hot"]], changed_groups=changed)
(ROOT / "docs/protofix/linked-identity-frozen.json").write_text(json.dumps(result, indent=2) + "\n")
assert not result["hot_changed"], result["hot_changed"]
assert not any("r7_run_loop" in row["name"] or
               "ExLoopT<true>::flip_control_pass" in row["name"] for row in changed)
print(json.dumps({key: value for key, value in result.items() if key != "changed_groups"}, indent=2))
