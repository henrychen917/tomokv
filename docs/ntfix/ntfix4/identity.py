#!/usr/bin/env python3
"""All emitted production bodies versus headline, with ntfix3 attribution."""
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
    name = r['name']
    if 'parse_and_dispatch<' in name:
        why = 'N3 pre-AUTH error exit and N4 cold frontier guard'
        if r['headline_changed_since_lane_base']:
            why += '; composed with wave3 dispatcher edits (read-local demotion / scatter prebuild)'
    elif 'resp_preauth_error(' in name:
        why = 'N3 cold pre-AUTH error classifier'
    elif 'IoLoop::epoll_recv(' in name:
        why = 'N1 epoll input counter and N4 cold frontier guard'
    elif re.search(r'Client::(?:query_buffer|read_space)', name):
        why = 'N4 conservative bound with cold frontier refinement; receive-helper outlining'
    elif re.search(r'IoLoop::(?:arm_recv<|drive_tls<|on_cqe|r7_on_recv<|query_buffer)', name):
        why = 'N4 cold frontier guard and receive-helper outlining in caller'
    elif 'WbEngine::pump_tls<' in name:
        why = 'N2 uring close wakeup / epoll ciphertext-output accounting'
    elif re.search(r'WbEngine::(?:pump_epoll\(|write_legacy_epoll\(|submit_tls_cipher<)', name):
        why = 'Epoll output-byte accounting'
    else:
        why = 'Source unedited by ntfix; compiler inlining/codegen after network-header composition'
    if r['admitted']:
        why += '; exact ntfix3 body'
    elif r['targets_equal']:
        why += '; headline relocation targets and offsets unchanged'
    return why


def one(obj):
    result = budget.compare(ROOT/'build'/obj, obj)
    base = budget.Bodies(ROOT/'build/pre-src/build'/obj)
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
               ('total','hot','hot_equal_headline','hot_equal_ntfix3','residual_hot','residual','changed')}
    summary['objects'] = len(objects)
    summary['handlers_changed'] = [r for r in rows if re.search(r'::cmd_\w+(?:<|\()',r['name'])]
    summary['residual_hot_bodies'] = [r for r in rows if r['hot'] and not r['admitted']]
    summary['reasons'] = dict(Counter(r['reason'] for r in rows))
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    for filename, selected in [('changed-bodies.md',rows),
                               ('changed-hot-bodies.md',[r for r in rows if r['hot']]),
                               ('residual-hot-bodies.md',summary['residual_hot_bodies'])]:
        lines=['# bce4eb0aa versus ntfix4','',
               'Canonical opcodes and resolved relocation targets use unchanged `ccfix_audit.py`.',
               'Zero bytes means not emitted. Identity attribution is not a merit verdict.','',
               '| Object | Function | Headline bytes | ntfix3 bytes | POST bytes | Reason |',
               '|---|---|---:|---:|---:|---|']
        for r in selected:
            lines.append(f"| `{r['object']}` | `{r['name']}` | {r['headline']} | {r['ntfix3']} | {r['post']} | {r['reason']} |")
        (OUT/filename).write_text('\n'.join(lines)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if not isinstance(v,(list,dict))}),flush=True)


if __name__=='__main__':
    main()
