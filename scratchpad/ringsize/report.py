#!/usr/bin/env python3
"""PRE vs POST from ab.sh's csv: median rate per arm per cell, with the two counters that say
whether the read-local mechanism fired at all beside every rate."""
import csv, statistics, sys

rows = list(csv.DictReader(open(sys.argv[1])))
cells = []
for r in rows:
    if r['cell'] not in cells:
        cells.append(r['cell'])

def med(cell, arm, field, cast=float):
    v = [cast(r[field]) for r in rows if r['cell'] == cell and r['arm'] == arm and r[field] not in ('', 'None')]
    return statistics.median(v) if v else float('nan')

label = {'r41': '41% reads (3:2)', 'r61': '61% reads (2:3)',
         'w100': 'write-only (1:0)', 'r100': 'read-only (0:1)'}
hdr = ('cell', 'arm', 'rate M/s', 'read_local_hits', 'fallback_inflight_write', 'local %')
print(f"{hdr[0]:<18}{hdr[1]:<6}{hdr[2]:>10}{hdr[3]:>18}{hdr[4]:>26}{hdr[5]:>10}")
for c in cells:
    for arm in ('PRE', 'POST'):
        rate = med(c, arm, 'rate')
        h = med(c, arm, 'read_local_hits')
        f = med(c, arm, 'read_local_fallback_inflight_write')
        tot = h + f
        pct = (100.0 * h / tot) if tot else float('nan')
        print(f"{label.get(c,c):<18}{arm:<6}{rate/1e6:>10.3f}{h:>18.0f}{f:>26.0f}{pct:>9.1f}%")
    pre, post = med(c, 'PRE', 'rate'), med(c, 'POST', 'rate')
    print(f"{'':<18}{'delta':<6}{(post-pre)/1e6:>+10.3f}{'':>18}{'':>26}{100.0*(post-pre)/pre:>+8.2f}%")
    print()

print("per-visit rates (drift check, M/s)")
print(f"{'cell':<18}" + "".join(f"{a:>9}" for a in ('R1 PRE','R1 PST','R1 PST','R1 PRE',
                                                    'R2 PRE','R2 PST','R2 PST','R2 PRE',
                                                    'R3 PRE','R3 PST','R3 PST','R3 PRE')))
for c in cells:
    seq = [r for r in rows if r['cell'] == c]
    seq.sort(key=lambda r: (int(r['round']), int(r['visit'])))
    print(f"{label.get(c,c):<18}" + "".join(f"{float(r['rate'])/1e6:>9.2f}" for r in seq))
