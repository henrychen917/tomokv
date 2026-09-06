#!/usr/bin/env python3
"""Slope-per-op table from measure.sh CSV rows.

Columns: tag,rep,shape,readpct,pipeline,N1,N2,iu1,ia1,rate1,iu2,ia2,rate2
Instructions per op is (I(N2)-I(N1))/(N2-N1): a slope, so anything outside the measured window
(boot, warm, idle spin) cancels.
"""
import sys, csv, collections, statistics

rows = collections.defaultdict(lambda: collections.defaultdict(list))
for path in sys.argv[1:]:
    with open(path) as f:
        for r in csv.reader(f):
            if len(r) < 9: continue
            tag, rep, shape, rp, pl, n1, n2 = r[:7]
            a = r[7].split(); b = r[8].split()
            if len(a) < 2 or len(b) < 2: continue
            iu1, ia1 = a[0], a[1]
            iu2, ia2 = b[0], b[1]
            n1, n2 = int(n1), int(n2)
            for kind, a, b in (("u", iu1, iu2), ("all", ia1, ia2)):
                try: slope = (float(b) - float(a)) / (n2 - n1)
                except ValueError: continue
                rows[(shape, int(rp), int(pl), kind)][tag].append(slope)

tags = []
for k in rows:
    for t in rows[k]:
        if t not in tags: tags.append(t)

print(f"{'shape':>5} {'read%':>5} {'pipe':>4} {'ctr':>3} " +
      " ".join(f"{t:>12}" for t in tags) + f" {'delta':>10} {'pct':>8}")
for key in sorted(rows, key=lambda k: (k[3], k[2], k[1], k[0])):
    shape, rp, pl, kind = key
    vals = [statistics.median(rows[key][t]) if rows[key].get(t) else float('nan') for t in tags]
    d = vals[1] - vals[0] if len(vals) > 1 else float('nan')
    p = 100.0 * d / vals[0] if len(vals) > 1 and vals[0] else float('nan')
    print(f"{shape:>5} {rp:>5} {pl:>4} {kind:>3} " +
          " ".join(f"{v:12.1f}" for v in vals) + f" {d:10.1f} {p:8.2f}%")
