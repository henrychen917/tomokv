#!/usr/bin/env python3
"""thrash.py CSV -- per cell: flips before/after the FIRST anchor (owner rule: thrash = moves after
stabilisation), time of first anchor, clients moved. Reads the ab.sh timelines next to the CSV."""
import csv, os, sys
SP = os.path.dirname(os.path.abspath(sys.argv[1]))
rows = list(csv.DictReader(open(sys.argv[1])))
print("%-3s %-6s %-6s %8s %10s %10s %6s %-14s" % ("rnd","arm","wl","anchor@s","flips-pre","flips-post","moved","phases"))
agg = {}
for r in rows:
    if r["fa"] != "1": continue
    tl = f"{SP}/fd-tl-{r['arm']}-{r['wl']}-{r['round']}.txt"
    if not os.path.exists(tl): continue
    first_anchor = None; flips_at_anchor = None; last = 0; phases = []
    for line in open(tl):
        f = line.split()
        if not f: continue
        t = int(f[0]); d = dict(kv.split(":", 1) for kv in f[1:] if ":" in kv and not kv.startswith("foreign"))
        st = d.get("flipctl_state"); fc = int(d.get("flip_completed", 0) or 0); last = fc
        ph = d.get("flipctl_phase", "?")
        if not phases or phases[-1] != ph: phases.append(ph)
        if first_anchor is None and st == "anchored":
            first_anchor = t; flips_at_anchor = fc
    pre = flips_at_anchor if flips_at_anchor is not None else last
    post = (last - flips_at_anchor) if flips_at_anchor is not None else 0
    key = (r["arm"], r["wl"]); a = agg.setdefault(key, [0, 0, 0, 0]); a[0] += pre; a[1] += post; a[2] += int(r["xfer"] or 0); a[3] += 1
    print("%-3s %-6s %-6s %8s %10d %10d %6s %s" % (r["round"], r["arm"], r["wl"], first_anchor if first_anchor is not None else "never", pre, post, r["xfer"], ">".join(p.replace("waiting-flip","flip") for p in phases)[:60]))
print("\nTOTAL per arm/wl: flips before first anchor / AFTER first anchor (thrash) / clients moved / cells")
for (arm, wl), (pre, post, moved, n) in sorted(agg.items()):
    print("  %-6s %-6s pre=%d post=%d moved=%d cells=%d" % (arm, wl, pre, post, moved, n))
