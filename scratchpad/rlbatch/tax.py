#!/usr/bin/env python3
"""Interleave tax = mix - homogeneous blend, per arm, from measure.sh rows."""
import sys, csv, collections, statistics
rows = collections.defaultdict(lambda: collections.defaultdict(list))
for path in sys.argv[1:]:
    for r in csv.reader(open(path)):
        if len(r) < 9: continue
        tag, rep, shape, rp, pl, n1, n2 = r[:7]
        a = r[7].split(); b = r[8].split()
        if len(a) < 2 or len(b) < 2: continue
        rows[(tag, shape, int(rp), int(pl))]["u"].append(
            (float(b[0]) - float(a[0])) / (int(n2) - int(n1)))
tags, pipes = [], []
for (tag, shape, rp, pl) in rows:
    if tag not in tags: tags.append(tag)
    if pl not in pipes: pipes.append(pl)
def med(tag, shape, rp, pl):
    v = rows.get((tag, shape, rp, pl), {}).get("u")
    return statistics.median(v) if v else None
for pl in sorted(pipes):
    rd = {t: med(t, "mix", 100, pl) for t in tags}
    wr = {t: med(t, "mix", 0, pl) for t in tags}
    if any(rd[t] is None or wr[t] is None for t in tags): continue
    print(f"\n--- pipeline {pl} ---")
    print(f"{'read%':>5} " + " ".join(f"{t+' mix':>13} {t+' blend':>13} {t+' tax':>11}" for t in tags))
    for rp in sorted({k[2] for k in rows if k[3] == pl and k[1] == "mix"} - {0, 100}):
        line = f"{rp:>5} "
        for t in tags:
            m = med(t, "mix", rp, pl)
            if m is None: line += " " * 40; continue
            f = rp / 100.0
            b = f * rd[t] + (1 - f) * wr[t]
            line += f"{m:13.1f} {b:13.1f} {m-b:+11.1f}"
        print(line)
    print(f"{'ctl':>5} " + " ".join(f"  rd={rd[t]:8.1f} wr={wr[t]:8.1f}            " for t in tags))
