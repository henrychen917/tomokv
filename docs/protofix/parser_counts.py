#!/usr/bin/env python3
"""Use the established instruction tracer on allocation-free inline/RESP parses."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
source = (ROOT / "tools/execindex_scope.py").read_text()
source = source.replace('"docs/execindex/instructions"', '"docs/protofix/parser-instructions"')
source = source.replace('"build/execindex/commands"', '"build/protofix/parser-commands"')
source = source.replace('"96-103"', '"0-15"')
scope = {"__file__": str(ROOT / "tools/execindex_scope.py"), "__name__": "protofix_parser_counter"}
exec(compile(source, scope["__file__"], "exec"), scope)
for arm, base in (("pre", ROOT / "build/protofix/pre-source"), ("post", ROOT)):
    folder = scope["BUILD"] / (arm + "-normal")
    folder.mkdir(parents=True, exist_ok=True)
    cmd = ["g++", "-std=c++20", "-O2", "-g", "-march=native", "-I" + str(base),
           str(ROOT / "docs/protofix/parser_scope.cc"), "-o", str(folder / "probe")]
    subprocess.run(cmd, check=True)
cases = [(arm, "normal", cmd, protocol, batch, 1, -1) for arm in ("pre", "post")
         for cmd in ("GET", "SET", "INCR") for protocol in ("inline", "resp") for batch in (1, 32)]
with ThreadPoolExecutor(4) as pool:
    rows = list(pool.map(scope["trace"], cases))
pairs = []
for row in rows:
    if row["arm"] != "post":
        continue
    old, = [r for r in rows if r["arm"] == "pre" and all(r[k] == row[k] for k in ("command", "mode", "batch"))]
    pairs.append({k: row[k] for k in ("command", "mode", "batch")} | dict(pre=old["total"], post=row["total"],
                 delta=row["total"] - old["total"], external_calls_equal=old["excluded"] == row["excluded"]))
scope["save"](scope["OUT"] / "comparison.json", pairs)
assert all(r["delta"] <= 0 and r["external_calls_equal"] for r in pairs)
assert all(r["delta"] == 0 for r in pairs if r["mode"] == "resp")
