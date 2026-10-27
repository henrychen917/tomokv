#!/usr/bin/env python3
"""Compile-only controls for affected units which retain GCC's default budget."""
import concurrent.futures,json
from pathlib import Path
import budgets
budgets.OUT.mkdir(parents=True,exist_ok=True);budgets.DOC.mkdir(parents=True,exist_ok=True)
units=[p+s for p in ('src/','db0/src/') for s in ('cmd/scripting.o','cmd/latency_tracking.o','cmd/slowlog.o','cmd/tracking.o','core/fliplisten.o','core/shutdown.o','core/lbplanner.o')]
jobs=[dict(arm='post',object=o,budget=n) for o in units for n in (9992,10000,10008)]
with concurrent.futures.ProcessPoolExecutor(16) as pool:rows=list(pool.map(budgets.trial,jobs))
out=budgets.ROOT/'docs/wave8b/unpinned-budgets.json'
out.write_text(json.dumps(rows,indent=2)+'\n')
for unit in units:
 r=[x for x in rows if x['object']==unit]
 print(unit,len({x['code_digest']for x in r}),'bodies',flush=True)
