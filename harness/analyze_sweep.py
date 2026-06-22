#!/usr/bin/env python3
"""v9 max-info sweep analysis. Aggregates ofat/inter/bench.tsv (drift-robust bracketed ratios,
median over reps) into a per-regime knob-effect table + interaction + bench-axis summary.
Usage: python3 analyze_sweep.py [/home/henry/Projects/v9_sweep]"""
import csv, sys, statistics
from collections import defaultdict

D = sys.argv[1] if len(sys.argv) > 1 else "/home/henry/Projects/v9_sweep"

def load(name):
    try:
        return list(csv.DictReader(open(f"{D}/{name}"), delimiter="\t"))
    except FileNotFoundError:
        return []

# ---- OFAT: per-regime per-knob-value median ratio ----
ofat = defaultdict(list)
for x in load("ofat.tsv"):
    try: ofat[(x["regime"], x["knob"].replace("thredis-",""), x["value"])].append(float(x["ratio"]))
    except: pass

regimes = sorted({k[0] for k in ofat})
print("="*78)
print("v9 MAX-INFO SWEEP — OFAT knob effects (median bracketed ratio; >1 helps, <1 hurts)")
print("="*78)
for reg in regimes:
    items = [(statistics.median(v), k, val, len(v)) for (r,k,val),v in ofat.items()
             if r==reg and len(v)>=2]
    sig = [t for t in items if abs(t[0]-1) >= 0.02]
    print(f"\n--- {reg} ---  ({len({k for _,k,_,_ in items})} knobs swept)")
    if not sig:
        print("  all knob values within +-2% (neutral)")
    for med,k,val,n in sorted(sig, reverse=True):
        print(f"  {k:26}={val:>6}  x{med:.3f}  ({'HELPS' if med>1 else 'HURTS'})  n={n}")

# ---- per-knob cross-regime summary (is the effect consistent or regime-gated?) ----
print("\n"+"="*78); print("CROSS-REGIME: each knob's best value per regime (regime-dependence)"); print("="*78)
knobs = sorted({k for (_,k,_) in ofat})
for k in knobs:
    line = []
    for reg in regimes:
        vals = [(statistics.median(v), val) for (r,kk,val),v in ofat.items() if r==reg and kk==k and len(v)>=2]
        if vals:
            best = max(vals);
            if abs(best[0]-1)>=0.02: line.append(f"{reg.split('_')[0]}:{best[1]}(x{best[0]:.2f})")
    if line: print(f"  {k:26} {' '.join(line)}")

# ---- interactions ----
inter = defaultdict(list)
for x in load("inter.tsv"):
    try: inter[(x["regime"], x["combo"])].append(float(x["ratio"]))
    except: pass
if inter:
    print("\n"+"="*78); print("INTERACTIONS (2-way combos vs default, median)"); print("="*78)
    for reg in regimes:
        rows = [(statistics.median(v), c) for (r,c),v in inter.items() if r==reg and len(v)>=2 and abs(statistics.median(v)-1)>=0.02]
        if rows:
            print(f"\n--- {reg} ---")
            for med,c in sorted(rows, reverse=True): print(f"  {c:28} x{med:.3f}")

# ---- bench axes (pipeline/clients curves) ----
bench = defaultdict(lambda: defaultdict(list))
for x in load("bench.tsv"):
    try: bench[(x["regime"],x["axis"])][x["value"]].append(float(x["ops"]))
    except: pass
if bench:
    print("\n"+"="*78); print("BENCH AXES (median ops/s by pipeline & clients)"); print("="*78)
    for (reg,axis),vals in sorted(bench.items()):
        pts = " ".join(f"{v}:{statistics.median(o)/1e6:.2f}M" for v,o in sorted(vals.items(), key=lambda x:int(x[0])))
        print(f"  {reg:14} {axis:9} {pts}")
print("\n(done)")
