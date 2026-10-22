#!/usr/bin/env python3
"""Refresh final xshard IPA sizes after the held-version overwrite correction."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import budgets_final as b

b.out = b.root / 'build/notifyorder/budgets-refresh'
b.report = b.root / 'docs/notifyorder/budgets-refresh'
b.out.mkdir(parents=True, exist_ok=True)
b.report.mkdir(parents=True, exist_ok=True)
baseline = json.loads((b.root / 'docs/notifyorder/budgets-final/sizes.json').read_text())
current = {'src/cmd/xshard.o': 128421, 'db0/src/cmd/xshard.o': 127094}
with ThreadPoolExecutor(max_workers=2) as pool:
    dumps = list(pool.map(lambda u: b.compile_one('post', u, current[u], True), b.units))
trials = []
for row in dumps:
    pre, = [r for r in baseline if r['arm'] == 'pre' and r['unit'] == row['unit']]
    budget = pre['budget'] + row['start_size'] - pre['start_size']
    row['derived_budget'] = budget
    trials.append(('post', row['unit'], budget))
with ThreadPoolExecutor(max_workers=2) as pool:
    compiled = list(pool.map(lambda args: b.compile_one(*args), trials))
results = [dict(r, **b.compare(r['unit'], r['object'])) for r in dumps + compiled]
(b.report / 'trials.json').write_text(json.dumps(results, indent=2)+'\n')
for row in results:
    print(json.dumps({k:v for k,v in row.items() if k not in ('bodies', 'command')}), flush=True)
