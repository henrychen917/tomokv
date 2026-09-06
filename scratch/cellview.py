#!/usr/bin/env python3
"""cellview.py MTFILE [TLFILE] [--all] -- per-second memtier rate with the controller phase
overlaid (from the ab.sh timeline), then mean ops/sec per phase. Localizes a loss in time."""
import re, sys
args = [a for a in sys.argv[1:] if not a.startswith("--")]
show_all = "--all" in sys.argv
mt = open(args[0], errors="replace").read().replace("\r", "\n")
rx = re.compile(r"\[RUN #\d+ +\d+%, +(\d+) secs\].*?(\d+) \(avg: +(\d+)\) ops/sec.*?([\d.]+) \(avg: +([\d.]+)\) msec")
per = {}
for m in rx.finditer(mt):
    s = int(m.group(1)); per[s] = (int(m.group(2)), float(m.group(4)))   # last sample for that second
phase = {}
if len(args) > 1:
    for line in open(args[1]):
        f = line.split()
        if not f: continue
        t = int(f[0]); d = dict(kv.split(":", 1) for kv in f[1:] if ":" in kv and not kv.startswith("foreign"))
        phase[t] = (d.get("flipctl_phase", "?"), d.get("flip_completed", "?"), d.get("flipctl_triggers", "?"))
def phase_at(s):
    best = None
    for t in sorted(phase):
        if t <= s: best = phase[t]
    return best or ("?", "?", "?")
byphase = {}
for s in sorted(per):
    ops, lat = per[s]; ph = phase_at(s)
    byphase.setdefault(ph[0], []).append(ops)
    if show_all: print("%3ds %8d ops/s %6.2f ms  phase=%-14s flips=%s trig=%s" % (s, ops, lat, ph[0], ph[1], ph[2]))
tot = [o for o, _ in per.values()]
print("cell mean %.0f over %d s; min %d @%ds" % (sum(tot)/len(tot), len(tot), min(tot), min(per, key=lambda k: per[k][0])) if tot else "no samples")
for ph, v in byphase.items():
    print("  phase %-14s %3d s  mean %8.0f  min %8d" % (ph, len(v), sum(v)/len(v), min(v)))
