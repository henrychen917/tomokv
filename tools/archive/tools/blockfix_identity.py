#!/usr/bin/env python3
"""Audit the actual MGET/MSET entry points as well as GET/SET handlers.

MGET/MSET dispatch through cmd_xshard_only and xshard_execute, not symbols named
cmd_mget/cmd_mset. Use the existing PSFIX relocation normalizer, including its
TLS relocation support; the separate strict linked audit retains TLS placement
differences rather than hiding them.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

import psfix_artifacts

ROOT = Path(__file__).resolve().parents[1]
PRE = Path(sys.argv[1])
HOT = re.compile(r'::cmd_(?:get|set)(?:\(|<)|::cmd_xshard_only|'
                 r'::xshard_(?:prepare|execute|complete|store_string|queue_commit|flush_commits)')
rows = []
for prefix in ('src', 'db0/src'):
    for unit in ('t_string', 'xshard'):
        relative = Path(prefix) / 'cmd' / (unit + '.o')
        before = psfix_artifacts.audit.Elf(PRE / relative)
        after = psfix_artifacts.audit.Elf(ROOT / 'build' / relative)
        old, new = before.functions(), after.functions()
        symbols = sorted(old)
        names = subprocess.check_output(['c++filt'], input='\n'.join(symbols) + '\n', text=True).splitlines()
        for symbol, name in zip(symbols, names):
            if not HOT.search(name):
                continue
            equal = symbol in new and before.canonical(old[symbol]) == after.canonical(new[symbol])
            rows.append(dict(object=str(relative), symbol=symbol, name=name,
                             pre_size=old[symbol]['size'], post_size=new.get(symbol, {}).get('size'),
                             relocation_equal=equal))
assert rows and any('::xshard_execute(' in r['name'] for r in rows)
report = dict(normalizer='tools/psfix_artifacts.py + tools/lbstall_artifacts.py',
              compared=len(rows), changed=[r for r in rows if not r['relocation_equal']], bodies=rows)
(ROOT / 'docs/blockfix/command-hot-identity.json').write_text(json.dumps(report, indent=2) + '\n')
print('Actual GET/SET/MGET/MSET execution bodies:', len(rows), 'changed:', len(report['changed']))
raise SystemExit(bool(report['changed']))
