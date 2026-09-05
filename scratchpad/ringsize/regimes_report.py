#!/usr/bin/env python3
"""PRE vs POST for the connection-footprint and MSET-width regimes.

DRAM fills per operation is the column this table exists for. Instructions per operation cannot
tell a bigger working set from more work: the ring costs +960 bytes on every armed connection, and
whether that is free or fatal is a question about fills, not about instructions.

    regimes_report.py <csv>
"""
import csv, statistics as st, sys

rows = list(csv.DictReader(open(sys.argv[1])))
NUM = ('rate', 'p50', 'p99', 'cmds', 'instr', 'cycles', 'fills', 'read_local_hits',
       'read_local_fallback_inflight_write', 'read_local_fallbacks', 'srv_cores', 'mux')
SHAPE = {}
for r in rows:
    for k in NUM:
        r[k] = float(r[k])
    c = r['cmds'] or 1.0
    r['instr_op'] = r['instr'] / c
    r['cyc_op'] = r['cycles'] / c
    r['fills_op'] = r['fills'] / c
    r['ipc'] = r['instr'] / r['cycles'] if r['cycles'] else float('nan')
    if r.get('threads') and r.get('conns'):
        t = int(float(r['threads'])); n = int(float(r['conns']))
        SHAPE[r['cell']] = f"{t} thr x {n // t}"

low = [r for r in rows if r['mux'] < 99.5]
if low:
    print(f"WARNING: {len(low)} row(s) multiplexed on the PMU -- three events on a shared counter\n")

cells = []
for r in rows:
    if r['cell'] not in cells:
        cells.append(r['cell'])

# Totals are what the footprint term depends on; the per-thread shape is recorded because it is
# NOT the shape the owner's rig uses (32 threads x 16 / x 64). Three load cores cannot hold 32
# generator threads cleanly, so the same totals are reached with eight threads.
LABEL = {'c512': '512 conns', 'c2048': '2048 conns',
         'm8': 'MSET 8 keys  (under the 16 bound)',
         'm32': 'MSET 32 keys (over it)'}

def label(c):
    base = LABEL.get(c, c)
    sh = SHAPE.get(c)
    return f"{base} ({sh})" if sh and c.startswith('c') else base

def med(cell, arm, field):
    v = [r[field] for r in rows if r['cell'] == cell and r['arm'] == arm]
    return st.median(v) if v else float('nan')

hdr = (f"{'cell':<34}{'arm':<6}{'M ops/s':>9}{'instr/op':>10}{'cyc/op':>9}{'IPC':>7}"
       f"{'fills/op':>10}{'p99 ms':>8}{'local %':>9}{'write-demoted':>15}{'srv cores':>10}")
print(hdr)
print('-' * len(hdr))
for c in cells:
    for arm in ('PRE', 'POST'):
        h = med(c, arm, 'read_local_hits')
        allf = med(c, arm, 'read_local_fallbacks')
        tot = h + allf
        pct = (100.0 * h / tot) if tot else float('nan')
        print(f"{label(c):<34}{arm:<6}{med(c,arm,'rate')/1e6:>9.3f}"
              f"{med(c,arm,'instr_op'):>10.1f}{med(c,arm,'cyc_op'):>9.1f}{med(c,arm,'ipc'):>7.3f}"
              f"{med(c,arm,'fills_op'):>10.3f}{med(c,arm,'p99'):>8.2f}"
              f"{(('%8.1f%%' % pct) if tot else '       --'):>9}"
              f"{med(c,arm,'read_local_fallback_inflight_write'):>15.0f}"
              f"{med(c,arm,'srv_cores'):>10.2f}")
    def d(fld):
        p, q = med(c, 'PRE', fld), med(c, 'POST', fld)
        return (q - p) / p * 100.0 if p else float('nan')
    print(f"{'':<34}{'delta':<6}{d('rate'):>+8.2f}%{d('instr_op'):>+9.2f}%"
          f"{d('cyc_op'):>+8.2f}%{d('ipc'):>+6.2f}%{d('fills_op'):>+9.2f}%")
    print()

# The question the connection regime was built to answer, stated as arithmetic rather than left to
# the reader: does the extra footprint cost more at the high connection count than at the low one?
if 'c512' in cells and 'c2048' in cells:
    def fills_delta(c):
        return med(c, 'POST', 'fills_op') - med(c, 'PRE', 'fills_op')
    lo, hi = fills_delta('c512'), fills_delta('c2048')
    print(f"FOOTPRINT TERM: POST adds {lo:+.3f} DRAM fills/op at 512 connections and "
          f"{hi:+.3f} at 2048.")
    if hi > lo:
        print(f"It grows with connection count by {hi - lo:+.3f} fills/op, which is the +960 bytes")
        print("per armed connection showing up as working set. Weigh it against the rate row above:")
        print("if the rate at 2048 is worse, the ring should grow on demand instead of standing at")
        print("the window.")
    else:
        print("It does not grow with connection count, so the ring's footprint is not what limits")
        print("this server at 2048 connections and static sizing to the window is not the problem.")
