#!/usr/bin/env python3
"""PRE vs POST from ab_triad.sh: the rate, the counters that say whether the mechanism fired at
all, the ring-overflow count, and instructions/op, cycles/op and IPC measured in the same window.

"local %" is the read-local HIT SHARE -- hits / (hits + writes-in-flight demotions) -- which is the
number the defect moves: an overflowed connection is disarmed, so every read on it is demoted and
that share collapses toward zero however few keys actually conflicted.

"ring ovf" is populated only by the instrumented binaries (validate.sh ovf phase); it reads 0 in
the clean runs because the counter is not compiled into them, which is not the same as zero
overflows. Read it only from the ovf table.

The read-only cell is the NULL CONTROL: a connection that never writes never activates the write
sidecar, so this change provably cannot reach it. Whatever that row reads is the resolution floor
of the whole table -- a rate delta smaller than the null's own drift is not a result."""
import csv, statistics, sys

rows = list(csv.DictReader(open(sys.argv[1])))
for r in rows:
    for k in ('rate', 'p50', 'p99', 'mux'):
        r[k] = float(r[k])
    for k in ('cmds', 'instr', 'cycles', 'read_local_hits',
              'read_local_fallback_inflight_write', 'read_local_fallbacks', 'ring_overflows',
              'srv_cores'):
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

# Named by WRITE fraction: the ring is a write structure and the defect is a write-ratio cliff.
label = {'w41': '41% writes  (under)', 'w55': '55% writes  (edge)',
         'w70': '70% writes  (over)',
         'w100': 'pure SET (1:0) NULL', 'r100': 'pure GET (0:1) NULL'}

hdr = (f"{'cell':<22}{'arm':<6}{'M ops/s':>9}{'instr/op':>10}{'cyc/op':>9}{'IPC':>7}"
       f"{'p99 ms':>8}{'local hits':>14}{'write-demoted':>15}{'local %':>9}"
       f"{'ring ovf':>11}{'srv cores':>11}")
print(hdr)
print('-' * len(hdr))
for c in cells:
    for arm in ('PRE', 'POST'):
        h = med(c, arm, 'read_local_hits')
        f = med(c, arm, 'read_local_fallback_inflight_write')
        # THE DENOMINATOR IS EVERY READ THAT WANTED TO BE LOCAL, not just the ones a write stopped.
        # Dividing by hits + write-demotions alone reports a share that cannot fall below what the
        # OTHER fallback reasons already took, and would read as 100% on a connection that lost
        # every read to something else. They coincide whenever in-flight writes dominate -- which is
        # exactly the regime this lane is about -- and that coincidence has to be shown, not assumed.
        allf = med(c, arm, 'read_local_fallbacks')
        tot = h + allf
        pct = (100.0 * h / tot) if tot else float('nan')
        print(f"{label.get(c, c):<22}{arm:<6}{med(c,arm,'rate')/1e6:>9.3f}"
              f"{med(c,arm,'instr_op'):>10.1f}{med(c,arm,'cyc_op'):>9.1f}{med(c,arm,'ipc'):>7.3f}"
              f"{med(c,arm,'p99'):>8.2f}{h:>14.0f}{f:>19.0f}"
              f"{('%8.1f%%' % pct) if tot else '       --':>9}"
              f"{med(c,arm,'ring_overflows'):>11.0f}{med(c,arm,'srv_cores'):>11.2f}")
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

unsat = [(c, a, med(c, a, 'srv_cores')) for c in cells for a in ('PRE', 'POST')
         if med(c, a, 'srv_cores') < 0.85]
if unsat:
    print("NOT SERVER-BOUND -- these cells burned well under the one server core they were")
    print("given, so their rate is somebody else's limit and only instructions/op can be read:")
    for c, a, v in unsat:
        print(f"    {label.get(c,c):<22}{a:<6}{v:>6.2f} cores")
    print()

null = [r['rate'] for r in rows if r['cell'] == 'r100']
if null:
    spread = 100.0 * (max(null) - min(null)) / statistics.median(null)
    print(f"\nNULL CONTROL SPREAD: the read-only cell moved {spread:.2f}% across all visits.")
    print("Any rate delta below that number is inside the instrument's own noise, and the")
    print("instructions/op column is the one that can still be read.")
