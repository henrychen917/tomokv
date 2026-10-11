#!/usr/bin/env python3
"""Exact opcode and relocation-target comparison using docs/ttlclean's ccfix auditor."""
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
from ccfix4_budget import inventory, compare

PRE, POST = ROOT / 'build/hexpread-pre', ROOT / 'build'
OUT = ROOT / 'docs/hexpread/final/identity'
OUT.mkdir(parents=True, exist_ok=True)


def allowed(row):
    # Existing bodies are allowed only for the named hash readers / expiry reads, plus the
    # separately reproduced OBJECT read defect. A changed write/storage helper is a failure.
    if row['object'].endswith(('/hexpread.o', '/objectpread.o')):
        return row['pre_size'] == 0
    return bool(re.search(r'::(?:cmd_hget|cmd_hmget|cmd_hlen|cmd_hexists|cmd_hstrlen|cmd_hscan|cmd_hrandfield|generic_getall|hash_get|hread_generic|hash_read_visit|hash_ttl_on_access|atomic_read_owns_value|cmd_object|cmd_object_notify)(?:<|\()', row['name']))


rows, totals, unchanged_objects = [], [], []
for path in sorted(list((PRE / 'src').rglob('*.o')) + list((PRE / 'db0/src').rglob('*.o'))):
    rel = path.relative_to(PRE)
    after = POST / rel
    assert after.exists(), after
    old, new = inventory(path), inventory(after)
    result = compare(old, new)
    totals.append(dict(object=str(rel), total=result['total'], changed=result['changed']))
    for row in result['rows']:
        row['object'] = str(rel)
        row['allowed_read_change'] = allowed(row)
        rows.append(row)
    print(rel, result['changed'], flush=True)
for ns in ('src', 'db0/src'):
    for unit in ('hexpread', 'objectpread'):
        rel = Path(ns) / 'cmd' / (unit + '.o')
        result = compare({}, inventory(POST / rel))
        totals.append(dict(object=str(rel), total=result['total'], changed=result['changed']))
        for row in result['rows']:
            row['object'] = str(rel)
            row['allowed_read_change'] = allowed(row)
            rows.append(row)

ordinary_pattern = re.compile(r'::(?:cmd_get|cmd_set|cmd_mget|cmd_mset|xshard_plain_prepare|xshard_plain_finish)(?:<|\()')
ordinary = [r for r in rows if ordinary_pattern.search(r['name'])]
violations = [r for r in rows if not r['allowed_read_change']]
summary = dict(pre_sha256=hashlib.sha256((PRE / 'tomokv').read_bytes()).hexdigest(),
               post_sha256=hashlib.sha256((POST / 'tomokv').read_bytes()).hexdigest(),
               total=sum(r['total'] for r in totals), changed=len(rows),
               changed_outside_read_scope=len(violations), ordinary_changed=len(ordinary),
               strict_pass=not violations, objects=totals,
               ordinary_changes=ordinary, outside_read_scope=violations)
(OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
(OUT / 'changed-functions.json').write_text(json.dumps(rows, indent=2) + '\n')
lines = ['# Changed emitted functions', '',
         'Exact opcodes plus relocation targets; no error-callee or instruction masking.', '',
         '| Object | Function | Bytes PRE → POST | Scope |', '|---|---|---|---|']
for r in rows:
    lines.append(f"| `{r['object']}` | `{r['name']}` | {r['pre_size']} → {r['post_size']} | {'read / added helper' if r['allowed_read_change'] else 'OUTSIDE requested scope'} |")
(OUT / 'changed-functions.md').write_text('\n'.join(lines) + '\n')
print(json.dumps({k: v for k, v in summary.items() if not isinstance(v, list)}), flush=True)
sys.exit(0 if summary['strict_pass'] else 1)
