#!/usr/bin/env python3
"""All emitted production bodies versus headline, with compat2 attribution."""
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import gzip
import json
from pathlib import Path
import re
import sys

import budget

ROOT = budget.ROOT
OUT = budget.OUT / 'identity'


def reason(r):
    sys.path.insert(0, str(ROOT / 'docs/compat2'))
    from identity_inventory import reason as original_reason
    category, why = original_reason(r)
    if 'parse_and_dispatch<' in r['name']:
        why += ' Composed with ntfix N3 cold length classifier and N4 cold query frontier.'
    elif r['headline_changed_since_lane_base']:
        why += ' This body also differs between ntfix headline and the compat2 base.'
    if r['admitted']:
        why += ' Exact compat2 body.'
    elif r['targets_equal']:
        why += ' Headline relocation targets and offsets unchanged.'
    return category + ': ' + why


def one(obj):
    result = budget.compare(ROOT/'build'/obj, obj)
    base = budget.Bodies(ROOT/'build/compat2/pre-source/build'/obj)
    head = budget.Bodies(budget.HEAD/'build'/obj)
    for r in result['rows']:
        a, b = base.canon(r['symbol']), head.canon(r['symbol'])
        r['headline_changed_since_lane_base'] = a != b
        r['reason'] = reason(r)
    return dict(object=obj, **result)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    objects = sorted(str(p.relative_to(ROOT/'build')) for base in ('src','db0/src')
                     for p in (ROOT/'build'/base).rglob('*.o'))
    with ProcessPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(one, objects))
    with gzip.open(OUT/'dual-reference.json.gz','wt') as f:
        json.dump(results,f,indent=2)
    rows = [r for result in results for r in result['rows']]
    summary = {k:sum(r[k] for r in results) for k in
               ('total','hot','hot_equal_headline','hot_equal_compat2','residual_hot','residual','changed')}
    summary['objects'] = len(objects)
    summary['handlers_changed'] = [r for r in rows if re.search(r'::cmd_\w+(?:<|\()',r['name'])]
    summary['residual_hot_bodies'] = [r for r in rows if r['hot'] and not r['admitted']]
    summary['reasons'] = dict(Counter(r['reason'] for r in rows))
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    for filename, selected in [('changed-bodies.md',rows),
                               ('changed-hot-bodies.md',[r for r in rows if r['hot']]),
                               ('residual-hot-bodies.md',summary['residual_hot_bodies'])]:
        lines=['# 8656f9fa9 versus compat2b','',
               'Canonical opcodes and resolved relocation targets use unchanged `ccfix_audit.py`.',
               'Zero bytes means not emitted. Identity attribution is not a merit verdict.','',
               '| Object | Function | Headline bytes | compat2 bytes | POST bytes | Reason |',
               '|---|---|---:|---:|---:|---|']
        for r in selected:
            lines.append(f"| `{r['object']}` | `{r['name']}` | {r['headline']} | {r['compat2']} | {r['post']} | {r['reason']} |")
        (OUT/filename).write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if not isinstance(v,(list,dict))}),flush=True)


if __name__=='__main__':
    main()
