#!/usr/bin/env python3
"""Run the established serverless production-command counter on lane CPUs.

Only artifact destinations and the taskset mask differ from execindex_scope.py;
the GDB counting/external-call accounting and production link order are unchanged.
"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "tools/execindex_scope.py").read_text()
source = source.replace('"docs/execindex/instructions"', '"docs/protofix/instructions"')
source = source.replace('"build/execindex/', '"build/protofix/')
source = source.replace('"96-103"', '"0-15"')
scope = {"__file__": str(ROOT / "tools/execindex_scope.py"), "__name__": "protofix_counter"}
exec(compile(source, scope["__file__"], "exec"), scope)
out = scope["OUT"]
(out / "counter-source.json").write_text(json.dumps(dict(
    original="tools/execindex_scope.py", transformed_sha256=hashlib.sha256(source.encode()).hexdigest(),
    transformations=["artifact paths execindex -> protofix", "taskset mask 96-103 -> 0-15"],
    scope="Named production routines in the linked exec_batch_prefetched command scope; external callees excluded and recorded."), indent=2) + "\n")
arms = sys.argv[1:] or ["pre", "post"]
for arm in arms:
    for ns in ("normal", "db0"):
        scope["build"](arm, ns)
cases = [(arm, ns, cmd, mode, batch, 1, -1)
         for arm in arms for ns in ("normal", "db0")
         for cmd in ("GET", "SET", "INCR") for mode in ("1s", "2s") for batch in (1, 32)]
with ThreadPoolExecutor(4) as pool:
    rows = list(pool.map(scope["trace"], cases))
scope["save"](out / "results.json", rows)
if set(arms) == {"pre", "post"}:
    keys = ("namespace", "command", "mode", "batch", "atomic", "threshold")
    pairs = []
    for row in rows:
        if row["arm"] != "post":
            continue
        old, = [r for r in rows if r["arm"] == "pre" and all(r[k] == row[k] for k in keys)]
        pairs.append({k: row[k] for k in keys} | dict(pre=old["total"], post=row["total"],
                     delta=row["total"] - old["total"], functions_equal=old["functions"] == row["functions"],
                     external_calls_equal=old["excluded"] == row["excluded"]))
    scope["save"](out / "comparison.json", pairs)
    assert len(pairs) == 24 and all(r["delta"] == 0 and r["functions_equal"] and r["external_calls_equal"] for r in pairs)
