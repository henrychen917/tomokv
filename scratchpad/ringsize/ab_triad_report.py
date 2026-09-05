#!/usr/bin/env python3
"""PRE vs POST from ab_triad.sh: the rate, the two read-local counters that say whether the
mechanism fired at all, and the instructions/op, cycles/op and IPC measured in the same window.

The read-only cell is the NULL CONTROL: a connection that never writes never activates the write
sidecar, so this change provably cannot reach it. Whatever that row reads is the resolution floor
of the whole table -- a rate delta smaller than the null's own drift is not a result."""
import csv, statistics, sys

rows = list(csv.DictReader(open(sys.argv[1])))
for r in rows:
    for k in ('rate', 'p50', 'p99', 'mux'):
        r[k] = float(r[k])
    for k in ('cmds', 'instr', 'cycles', 'read_local_hits',
              'read_local_fallback_inflight_write', 'read_local_fallbacks'):
        r[k] = float(r[k])
    r['instr_op'] = r['instr'] / r['cmds'] if r['cmds'] else float('nan')
    r['cyc_op'] = r['cycles'] / r['cmds'] if r['cmds'] else float('nan')
    r['ipc'] = r['instr'] / r['cycles'] if r['cycles'] else float('nan')

low = [r for r in rows if r['mux'] < 99.5]
if low:
    print(f"WARNING: {len(low)} row(s) multiplexed on the PMU\n")

cells = []
for r in rows:
    if r['cell'] not in cells:
        cells.append(r['cell'])

def med(cell, arm, field):
    v = [r[field] for r in rows if r['cell'] == cell and r['arm'] == arm]
    return statistics.median(v) if v else float('nan')

label = {'r41': '41% reads (3:2)', 'r61': '61% reads (2:3)',
         'w100': 'write-only (1:0)', 'r100': 'read-only (0:1) NULL'}

hdr = (f"{'cell':<22}{'arm':<6}{'M ops/s':>9}{'instr/op':>10}{'cyc/op':>9}{'IPC':>7}"
       f"{'p99 ms':>8}{'local hits':>14}{'inflight fallback':>19}{'local %':>9}")
print(hdr)
print('-' * len(hdr))
for c in cells:
    for arm in ('PRE', 'POST'):
        h, f = med(c, arm, 'read_local_hits'), med(c, arm, 'read_local_fallback_inflight_write')
        tot = h + f
        pct = (100.0 * h / tot) if tot else float('nan')
        print(f"{label.get(c, c):<22}{arm:<6}{med(c,arm,'rate')/1e6:>9.3f}"
              f"{med(c,arm,'instr_op'):>10.1f}{med(c,arm,'cyc_op'):>9.1f}{med(c,arm,'ipc'):>7.3f}"
              f"{med(c,arm,'p99'):>8.2f}{h:>14.0f}{f:>19.0f}"
              f"{('%8.1f%%' % pct) if tot else '       --':>9}")
    d = lambda fld: (med(c, 'POST', fld) - med(c, 'PRE', fld)) / med(c, 'PRE', fld) * 100.0
    print(f"{'':<22}{'delta':<6}{d('rate'):>+8.2f}%{d('instr_op'):>+9.2f}%{d('cyc_op'):>+8.2f}%"
          f"{d('ipc'):>+6.2f}%")
    print()

print("per-visit rates (drift check, M ops/s) -- visits run PRE POST POST PRE within each round")
order = sorted({(int(r['round']), int(r['visit'])) for r in rows})
print(f"{'cell':<22}" + "".join(f"{'r%d.%s' % (rd, {1:'A',2:'B',3:'B',4:'A'}[vi]):>8}"
                                for rd, vi in order))
for c in cells:
    seq = sorted((r for r in rows if r['cell'] == c),
                 key=lambda r: (int(r['round']), int(r['visit'])))
    print(f"{label.get(c,c):<22}" + "".join(f"{r['rate']/1e6:>8.2f}" for r in seq))

null = [r['rate'] for r in rows if r['cell'] == 'r100']
if null:
    spread = 100.0 * (max(null) - min(null)) / statistics.median(null)
    print(f"\nNULL CONTROL SPREAD: the read-only cell moved {spread:.2f}% across all visits.")
    print("Any rate delta below that number is inside the instrument's own noise, and the")
    print("instructions/op column is the one that can still be read.")
