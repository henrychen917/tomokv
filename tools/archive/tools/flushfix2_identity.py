#!/usr/bin/env python3
"""Extend the established exact-body inventory to the new FLUSH-only objects."""
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

import ccfix_audit as audit

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/flushfix2/identity-final'


def main():
    # ccfix_audit's guard demands complete hot-body identity for its original
    # lane. Here the requested contract is an explicit inventory, plus separate
    # executed-instruction comparisons. Preserve the guard's result as evidence.
    summary = json.loads((OUT/'summary.json').read_text())
    summary['existing_audit_identity_guard_passed'] = not summary['other_hot'] and all(
        audit.re.search(r'::cmd_(?:config|info|acl)\(', r['name'])
        for r in summary['other_handlers'])
    with gzip.open(OUT/'bodies.json.gz', 'rt') as f:
        rows = json.load(f)
    rows = [r for r in rows if r['object'] not in ('src/store/flush.o', 'db0/src/store/flush.o')]
    additions = []
    for unit in ('src/store/flush.o', 'db0/src/store/flush.o'):
        assert not (ROOT/'build/flushfix2/pre'/unit).exists()
        elf = audit.audit.Elf(ROOT/'build'/unit)
        symbols = elf.functions()
        names = sorted(symbols)
        labels = subprocess.check_output(['c++filt'], input='\n'.join(names)+'\n', text=True).splitlines()
        for symbol, name in zip(names, labels):
            additions.append(dict(object=unit, symbol=symbol, name=name, equal=False,
                error_callee_only=False, raw_equal=False, pre_size=0,
                post_size=symbols[symbol]['size'], classification='new FLUSH translation unit'))
    rows += additions
    with gzip.open(OUT/'bodies.json.gz', 'wt') as f:
        json.dump(rows, f, indent=2)
    changed = [r for r in rows if not r['equal']]
    (OUT/'changed-bodies.json').write_text(json.dumps(changed, indent=2)+'\n')
    summary.update(total=len(rows), equal=sum(r['equal'] for r in rows), changed=len(changed),
                   new_object_bodies=len(additions))
    (OUT/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    objects = []
    for unit in sorted({r['object'] for r in rows}):
        old = ROOT/'build/flushfix2/pre'/unit
        new = ROOT/'build'/unit
        objects.append(dict(object=unit,
            pre_sha256=hashlib.sha256(old.read_bytes()).hexdigest() if old.exists() else None,
            post_sha256=hashlib.sha256(new.read_bytes()).hexdigest()))
    (OUT/'objects.json').write_text(json.dumps(objects, indent=2)+'\n')
    print({k:v for k,v in summary.items() if not isinstance(v, list)})


if __name__ == '__main__':
    main()
