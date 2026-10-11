#!/usr/bin/env python3
"""For every changed hot body attributed to several lanes (B), test whether its relocation-target
multiset is the additive composition PRE + sum(lane - B0) (lane deltas measured on each lane's own
branch). Reports non-additive targets per body."""
import json, sys
from collections import Counter
sys.path.insert(0, '.')
import attribute as A
r = json.load(open(sys.argv[1]))
merged = A.WT / 'build'
out = []
for o in r:
    rows = [x for x in o['rows'] if x['hot'] and (len(x['lanes_changed']) > 1 or x.get('r7_mirror_of') or
            (x['lanes_changed'] and not (set(x['merged_equals_lane']) & set(x['lanes_changed']))))]
    if not rows: continue
    obj = o['object']
    m, b1, b0 = A.Lazy(merged / obj), A.ref(A.B1 / obj), A.ref(A.B0 / obj)
    lanes = {l: A.ref(A.LANE_DIRS[l] / obj) for l in A.LANES}
    T = lambda lz, s: Counter(repr(t[2]) for t in (lz.canon(s) or (b'', []))[1])
    for x in rows:
        s = x['symbol']
        changers = x['lanes_changed'] or []
        expect = T(b1, s).copy()
        for l in changers:
            d = T(lanes[l], s); d.subtract(T(b0, s))
            expect.update(d)
        got = T(m, s)
        keys = set(expect) | set(got)
        dev = {k: (expect[k], got[k]) for k in keys if expect[k] != got[k]}
        out.append(dict(object=obj, name=x['name'], lanes=changers, r7=x.get('r7_mirror_of'),
                        deviations=len(dev), detail={k[:90]: v for k, v in sorted(dev.items())[:8]}))
        print(f"{obj:26} lanes={'+'.join(changers) or '-':34} dev={len(dev):2} {x['name'][:80]}")
json.dump(out, open(sys.argv[2], 'w'), indent=1)
