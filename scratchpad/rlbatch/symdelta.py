#!/usr/bin/env python3
"""Per-symbol instructions/op from two sample files, and the interleave tax against a blend.

  symdelta.py <period> <N1> <N2> <dir> <tag> <pipeline> <readpct>...
Reads <tag>-mix-<rp>-<pl>-<N>.sym plus the homogeneous controls mix-100 and mix-0, and prints
per symbol:  mix  -  (f*read_only + (1-f)*write_only).
"""
import sys, os, collections

period = int(sys.argv[1]); n1 = int(sys.argv[2]); n2 = int(sys.argv[3])
d = sys.argv[4]; tag = sys.argv[5]; pl = sys.argv[6]
rps = [int(x) for x in sys.argv[7:]]

def slope(shape, rp):
    out = collections.Counter()
    for n, sign in ((n2, 1), (n1, -1)):
        p = os.path.join(d, f"{tag}-{shape}-{rp}-{pl}-{n}.sym")
        if not os.path.exists(p): return None
        for line in open(p):
            f = line.rstrip("\n").split("\t")
            if len(f) < 3: continue
            out[f[2][:110]] += sign * int(f[0]) * period
    return {k: v / (n2 - n1) for k, v in out.items()}

rd = slope("mix", 100); wr = slope("mix", 0)
if rd is None or wr is None:
    print("missing homogeneous controls"); sys.exit(1)
print(f"read-only total  {sum(rd.values()):9.1f} instr/op")
print(f"write-only total {sum(wr.values()):9.1f} instr/op")
for rp in rps:
    mx = slope("mix", rp)
    if mx is None: continue
    f = rp / 100.0
    keys = set(mx) | set(rd) | set(wr)
    rows = []
    for k in keys:
        base = f * rd.get(k, 0.0) + (1 - f) * wr.get(k, 0.0)
        rows.append((mx.get(k, 0.0) - base, mx.get(k, 0.0), base, k))
    rows.sort(reverse=True)
    tot_mix = sum(mx.values()); tot_base = f * sum(rd.values()) + (1 - f) * sum(wr.values())
    print(f"\n=== read {rp}%  pipe {pl}: mix {tot_mix:.1f} vs blend {tot_base:.1f} "
          f"= tax {tot_mix - tot_base:+.1f} instr/op ===")
    print(f"{'delta':>9} {'mix':>9} {'blend':>9}  symbol")
    for delta, m, b, k in rows[:16]:
        if abs(delta) < 3: continue
        print(f"{delta:9.1f} {m:9.1f} {b:9.1f}  {k}")
    print("  ... negatives ...")
    for delta, m, b, k in rows[-8:]:
        if abs(delta) < 3: continue
        print(f"{delta:9.1f} {m:9.1f} {b:9.1f}  {k}")
