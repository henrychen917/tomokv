#!/usr/bin/env python3
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from budgets import compile_one, compare
pairs = [("src/cmd/xshard.o", n) for n in (128280, 128320, 128400, 128550)]
pairs += [("db0/src/cmd/xshard.o", n) for n in (126950, 127000, 127100, 127250)]
with ThreadPoolExecutor(8) as pool:
    compiled = list(pool.map(lambda x: compile_one("post", *x), pairs))
rows=[]
for r in compiled:
    r.update(compare(r["unit"], r["object"]))
    rows.append(r)
    print(r["unit"],r["budget"],r["hot"],r["spillover"],flush=True)
Path("docs/moverfix/identity-budgets/refine.json").write_text(json.dumps(rows, indent=2)+"\n")
