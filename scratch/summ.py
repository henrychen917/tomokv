#!/usr/bin/env python3
"""summ.py CSV -- per (workload, arm): cells, mean rate, spread, flips, clients moved, triggers,
holds, round trips; rate relative to the same-binary controller-OFF cells (pol0a+pol0b)."""
import csv, sys, statistics as st
from collections import defaultdict
rows = list(csv.DictReader(open(sys.argv[1])))
g = defaultdict(list)
for r in rows:
    if r["rate"] in ("MISSING", ""): continue
    g[(r["wl"], r["arm"])].append(r)
wls = []
for r in rows:
    if r["wl"] not in wls: wls.append(r["wl"])
def f(x):
    try: return float(x)
    except: return 0.0
def i(x):
    try: return int(float(x))
    except: return 0
print("%-6s %-7s %2s %10s %7s %8s %5s %6s %5s %5s %4s %-14s %s" % ("wl","arm","n","rate","vs-off","spread","comp","xfer","trig","hold","rt","anchor(s)","busy(io/ex) mean"))
for wl in wls:
    off = [f(r["rate"]) for a in ("pol0a","pol0b") for r in g.get((wl,a),[])]
    off_mean = st.mean(off) if off else 0
    for arm in ("pol0a","pol0b","pol1","guard1","base1"):
        rs = g.get((wl,arm))
        if not rs: continue
        rates = [f(r["rate"]) for r in rs]
        m = st.mean(rates)
        spread = (max(rates)-min(rates))/m if m else 0
        comp = sum(i(r["comp"]) for r in rs); xfer = sum(i(r["xfer"]) for r in rs)
        trig = sum(i(r["trig"]) for r in rs); hold = sum(i(r["hold"]) for r in rs); rt = sum(i(r.get("rt","0")) for r in rs)
        anchors = ",".join(sorted(set(r["anchor"] for r in rs)))
        busy = {}
        for r in rs:
            for kv in r["busy"].split(";"):
                for part in kv.split(","):
                    if "=" in part:
                        k,v = part.split("="); busy.setdefault(k,[]).append(f(v))
        busy_s = " ".join("%s=%.2f" % (k, st.mean(v)) for k,v in sorted(busy.items()))
        rel = (m/off_mean-1)*100 if off_mean else 0
        print("%-6s %-7s %2d %10.0f %+6.1f%% %7.1f%% %5d %6d %5d %5d %4d %-14s %s" % (wl,arm,len(rs),m,rel,spread*100,comp,xfer,trig,hold,rt,anchors,busy_s))
    print()
