#!/usr/bin/env python3
"""iowake function-body identity between PRE and POST production objects (no server, no rates).

Reuses tools/snapfix_identity.py's normalization (relocations, intra-function offsets, clone
numbers, alignment padding) with this lane's arms, then marks every changed, added or removed
function that matches the established hot-body selection (tools/lbstall_artifacts.py HOT).
Output: docs/iowake/identity/functions.json and docs/iowake/identity/changed.json.
"""
import json
from pathlib import Path
import subprocess

import lbstall_artifacts
import snapfix_identity as base

ROOT = Path(__file__).resolve().parents[1]
base.ARMS = {'pre': (ROOT / 'build/iowake/pre-source', ROOT / 'build/iowake/pre'),
             'post': (ROOT, ROOT / 'build')}
base.OUT = ROOT / 'docs/iowake/identity'
base.rename = lambda text: text  # snapfix's PRE-only symbol rename does not apply here


def main():
    base.main()
    report = json.loads((base.OUT / 'functions.json').read_text())
    rows = []
    for obj, r in report.items():
        for kind in ('changed', 'padding_only', 'added', 'removed'):
            names = r[kind]
            labels = subprocess.check_output(['c++filt'], input='\n'.join(names), text=True)\
                .splitlines() if names else []
            for symbol, label in zip(names, labels):
                rows.append(dict(object=obj, kind=kind, symbol=symbol, name=label,
                                 hot=bool(lbstall_artifacts.HOT.search(label))))
    (base.OUT / 'changed.json').write_text(json.dumps(rows, indent=2) + '\n')
    for row in rows:
        if row['kind'] != 'padding_only':
            print(('HOT ' if row['hot'] else 'cold'), row['kind'], row['object'], row['name'][:160])


if __name__ == '__main__':
    main()
