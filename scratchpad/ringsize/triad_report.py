#!/usr/bin/env python3
"""PRE vs POST from measure_triad.sh: instructions/op, cycles/op and IPC, all by the SLOPE between
two operation counts so setup, warm and out-of-window spin cancel.

Every cell prints all three factors side by side. A change that removes instructions but not cycles
is a change that removed nothing; a change that moves cycles with no instruction delta is the box
talking, not the code."""
import csv, statistics, sys

rows = [r for r in csv.DictReader(open(sys.argv[1]))]
for r in rows:
    for k in ('instr_u', 'cycles_u', 'instr_all', 'cycles_all', 'n'):
        r[k] = float(r[k])
    r['mux'] = float(r['mux'])

low = [r for r in rows if r['mux'] < 99.5]
if low:
    print(f"WARNING: {len(low)} row(s) multiplexed on the PMU (min {min(r['mux'] for r in low)}%)\n")

DOMAIN = sys.argv[2] if len(sys.argv) > 2 else 'all'      # 'all' = the whole core, 'u' = user only
I, C = ('instr_' + DOMAIN, 'cycles_' + DOMAIN)

def key(r):
    return (r['shape'], r['readpct'], r['pipe'])

cells = []
for r in rows:
    if key(r) not in cells:
        cells.append(key(r))

def slopes(cell, arm):
    """One (instr/op, cycles/op) pair per rep, from that rep's own two operation counts."""
    out = []
    reps = sorted({r['rep'] for r in rows if key(r) == cell and r['tag'] == arm})
    for rep in reps:
        sel = [r for r in rows if key(r) == cell and r['tag'] == arm and r['rep'] == rep]
        by_n = {}
        for r in sel:
            by_n.setdefault(r['n'], []).append(r)
        ns = sorted(by_n)
        if len(ns) < 2:
            continue
        lo, hi = ns[0], ns[-1]
        for a in by_n[lo]:
            for b in by_n[hi]:
                dn = b['n'] - a['n']
                out.append(((b[I] - a[I]) / dn, (b[C] - a[C]) / dn))
    return out

lab = {'mix': 'mix', 'sep': 'sep'}
print(f"instructions/op, cycles/op and IPC by slope ({DOMAIN} domain), median over reps\n")
hdr = f"{'cell':<16}{'instr PRE':>10}{'instr POST':>11}{'d%':>8}   {'cyc PRE':>9}{'cyc POST':>9}{'d%':>8}   {'IPC PRE':>8}{'IPC POST':>9}"
print(hdr)
print('-' * len(hdr))
for c in cells:
    pre, post = slopes(c, 'PRE'), slopes(c, 'POST')
    if not pre or not post:
        continue
    ipre, cpre = statistics.median(x[0] for x in pre), statistics.median(x[1] for x in pre)
    ipost, cpost = statistics.median(x[0] for x in post), statistics.median(x[1] for x in post)
    name = f"{lab[c[0]]} {c[1]}% p{c[2]}"
    print(f"{name:<16}{ipre:>10.1f}{ipost:>11.1f}{100*(ipost-ipre)/ipre:>+8.2f}   "
          f"{cpre:>9.1f}{cpost:>9.1f}{100*(cpost-cpre)/cpre:>+8.2f}   "
          f"{ipre/cpre:>8.3f}{ipost/cpost:>9.3f}")
