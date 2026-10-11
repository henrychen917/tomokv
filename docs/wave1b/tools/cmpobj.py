#!/usr/bin/env python3
"""List function bodies that differ between two object files (ccfix_audit canonical form:
opcodes + resolved relocation targets). usage: cmpobj.py A.o B.o"""
import subprocess, sys
from pathlib import Path
sys.path.insert(0, '/home/user/Projects/cx-wave1b/tools')
import ccfix_audit  # noqa: F401  (patches the canonical form)
import lbstall_artifacts as audit
a, b = audit.Elf(Path(sys.argv[1])), audit.Elf(Path(sys.argv[2]))
fa, fb = a.functions(), b.functions()
names = sorted(set(fa) | set(fb))
labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
n = 0
for sym, name in zip(names, labels):
    ca = a.canonical(fa[sym]) if sym in fa else None
    cb = b.canonical(fb[sym]) if sym in fb else None
    if ca != cb:
        n += 1
        kind = 'only-A' if cb is None else 'only-B' if ca is None else ('reloc' if ca[0] == cb[0] else 'code')
        hot = 'HOT ' if audit.HOT.search(name) else ''
        print(f"{kind:6} {hot}{fa[sym]['size'] if sym in fa else 0}->{fb[sym]['size'] if sym in fb else 0} {name[:150]}")
print(f'{n} differing of {len(names)}')
