#!/usr/bin/env python3
"""Audit every function in changed objects using lbstall's canonicalizer.

The stock hot-body compare is run separately and unchanged. The broader inventory
also contains TLS accesses (ELF R_X86_64_TPOFF32, type 23). Teach its width table
that four-byte relocation; preserve the original symbol/addend/target comparison.
"""
import inspect
import json
from pathlib import Path
import subprocess
import sys
import textwrap
sys.path.insert(0, 'tools')
import lbstall_artifacts as audit

source = textwrap.dedent(inspect.getsource(audit.Elf.canonical))
assert source.count('24: 8,') == 1
scope = vars(audit).copy()
exec(source.replace('24: 8,', '23: 4, 24: 8,'), scope)
audit.Elf.canonical = scope['canonical']
changed = []
pre = Path('build/gt13split-pre')
for path in sorted(pre.rglob('*.o')):
    rel = path.relative_to(pre)
    if path.read_bytes() != (Path('build') / rel).read_bytes():
        changed.append(str(rel))
assert changed == ['db0/src/cmd/xshard.o', 'src/cmd/xshard.o'], changed
Path('docs/gt13split/changed-objects.json').write_text(json.dumps(changed, indent=2) + '\n')
rows = []
for rel in changed:
    before, after = audit.Elf(pre / rel), audit.Elf(Path('build') / rel)
    old, new = before.functions(), after.functions()
    assert old.keys() == new.keys(), 'changed function inventory'
    names = list(old)
    demangled = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    for name, label in zip(names, demangled):
        if before.canonical(old[name]) != after.canonical(new[name]):
            row = dict(object=rel, symbol=name, name=label,
                       pre_size=old[name]['size'], post_size=new[name]['size'])
            rows.append(row)
            print(json.dumps(row), flush=True)
    print(rel, len(old), 'functions audited', flush=True)
Path('docs/gt13split/changed-bodies.json').write_text(json.dumps(rows, indent=2) + '\n')
assert rows and all('multi_' in row['name'] for row in rows), rows
