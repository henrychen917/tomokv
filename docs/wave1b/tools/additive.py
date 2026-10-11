#!/usr/bin/env python3
"""wave1b: call-structure additivity of every changed HOT body in one candidate object
(adapted from cx-wave1 docs/wave1/tools/additivity.py). For a body changed by one or more lanes, the
expected relocation-target multiset is PRE + sum(lane POST - B0) over the lanes that changed it; the
score counts targets whose multiplicity deviates. A lane-identical body scores 0 by construction.
savefix's delta is excluded for parse_and_dispatch (no savefix source change there; its delta is drift).
usage: additive.py <obj-rel> <candidate.o> [<candidate.o> ...]"""
import sys
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import attribute as A

obj = sys.argv[1]
b1, b0 = A.ref(A.B1 / obj), A.ref(A.B0 / obj)
lanes = {l: A.ref(A.LANE_DIRS[l] / obj) for l in A.LANES}
T = lambda lz, s: Counter(repr(t[2]) for t in (lz.canon(s) or (b'', []))[1])
for path in sys.argv[2:]:
    m = A.Lazy(Path(path)); m.load(); b1.load(); b0.load()
    names = sorted(set(m.funcs) | set(b1.funcs))
    import subprocess
    labels = subprocess.check_output(['c++filt'], input='\n'.join(names) + '\n', text=True).splitlines()
    total = bodies = 0
    detail = []
    for sym, name in zip(names, labels):
        hot = bool(A.audit.HOT.search(name) or A.HOT_RUN.search(name))
        if not hot:
            continue
        cm, c1 = m.canon(sym), b1.canon(sym)
        if cm == c1:
            continue
        c0 = b0.canon(sym)
        changers = [l for l, lz in lanes.items() if lz.canon(sym) != c0]
        # savefix made no source change in the dispatch bodies: its lane-branch delta there is
        # inlining drift (savefix report), which the integration must NOT reproduce.
        if 'parse_and_dispatch' in name:
            changers = [l for l in changers if l != 'savefix']
        expect = T(b1, sym).copy()
        for l in changers:
            d = T(lanes[l], sym); d.subtract(T(b0, sym)); expect.update(d)
        got = T(m, sym)
        dev = sum(abs(expect[k] - got[k]) for k in set(expect) | set(got))
        bodies += 1; total += dev
        if dev:
            detail.append(f"    dev={dev:3} lanes={'+'.join(changers) or '-'} {name[:110]}")
            if __import__('os').environ.get('TARGETS'):
                for k in sorted(set(expect) | set(got)):
                    if expect[k] != got[k]:
                        detail.append(f"        expected {expect[k]:2} got {got[k]:2}  {k[:120]}")
    print(f"{path}: hot changed {bodies}, non-additive target deviations {total}")
    print('\n'.join(detail[:int(__import__('os').environ.get('SHOW', '8'))]))
