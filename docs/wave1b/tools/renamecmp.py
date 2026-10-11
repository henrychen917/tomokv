#!/usr/bin/env python3
"""wave1b: compare the climon fix's renamed drain instantiations (extra `bool retire_plain`) with the
previous signatures, after mapping old -> new mangled names in symbols and relocation targets.
usage: renamecmp.py <old.o> <new.o>   (ccfix_audit canonical form; prints per-pair equality)"""
import re, subprocess, sys
from pathlib import Path
sys.path.insert(0, '/home/user/Projects/cx-wave1b/tools')
import ccfix_audit  # noqa: F401
import lbstall_artifacts as audit

RENAMES = [('serve_suppressing_implERNS_6ClientEbPb', 'serve_suppressing_implERNS_6ClientEbPbb'),
           ('17serve_suppressingERNS_6ClientE', '17serve_suppressingERNS_6ClientEb'),
           ('19prepare_suppressingERNS_6ClientERb', '19prepare_suppressingERNS_6ClientERbb')]

def rename(text):
    for old, new in RENAMES:
        text = re.sub(re.escape(old) + r'(?!b)', new, text)
    return text

def deep(v):
    if isinstance(v, str): return rename(v)
    if isinstance(v, tuple): return tuple(deep(x) for x in v)
    return v

a, b = audit.Elf(Path(sys.argv[1])), audit.Elf(Path(sys.argv[2]))
fa, fb = a.functions(), b.functions()
for sym in sorted(fa):
    if 'suppressing' not in sym:
        continue
    new = rename(sym)
    if new not in fb:
        print('MISSING', sym); continue
    ca, cb = a.canonical(fa[sym]), b.canonical(fb[new])
    ca = (ca[0], [deep(t) for t in ca[1]])
    label = subprocess.check_output(['c++filt', new], text=True).strip()
    same_code = ca[0] == cb[0]
    same_targets = sorted(map(repr, (t[2] for t in ca[1]))) == sorted(map(repr, (t[2] for t in cb[1])))
    print(f"{'EQUAL' if ca == cb else 'DIFF '} code={'same' if same_code else 'diff'} targets={'same' if same_targets else 'diff'} "
          f"{fa[sym]['size']}->{fb[new]['size']} {label[:130]}")
