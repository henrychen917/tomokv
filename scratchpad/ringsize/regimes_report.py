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

# THE MSET REGIME'S QUESTION IS WITHIN AN ARM, NOT BETWEEN THEM. A blind MSET naming more than
# kMaxPreciseKeysetKeys keys never refines, in either arm: it stays PendingWrite::Overflow and
# fences every pending read on the connection (src/net/rob.h:477). Both arms therefore go
# conservative at 32 keys and both stay precise at 8, so a PRE/POST delta here is expected to be
# nothing and would say nothing if it were not. What prices the bound is the drop from 8 keys to 32
# INSIDE one arm: that is what a connection loses by crossing it, and therefore what raising it to
# the ring capacity would buy.
if 'm8' in cells and 'm32' in cells:
    print("WHAT THE 16-KEY BOUND COSTS, within each arm (8 keys -> 32 keys):")
    print(f"{'arm':<6}{'M ops/s 8':>11}{'M ops/s 32':>12}{'rate':>9}"
          f"{'local% 8':>10}{'local% 32':>11}{'share lost':>12}{'demoted 8':>12}{'demoted 32':>13}")
    for arm in ('PRE', 'POST'):
        def share(c):
            h = med(c, arm, 'read_local_hits'); a = med(c, arm, 'read_local_fallbacks')
            return 100.0 * h / (h + a) if (h + a) else float('nan')
        r8, r32 = med('m8', arm, 'rate') / 1e6, med('m32', arm, 'rate') / 1e6
        s8, s32 = share('m8'), share('m32')
        print(f"{arm:<6}{r8:>11.3f}{r32:>12.3f}{100*(r32/r8-1):>+8.2f}%"
              f"{s8:>9.1f}%{s32:>10.1f}%{s32-s8:>+11.1f}pp"
              f"{med('m8',arm,'read_local_fallback_inflight_write'):>12.0f}"
              f"{med('m32',arm,'read_local_fallback_inflight_write'):>13.0f}")
    print("A share that barely moves means the bound is not what limits wide writes here and the")
    print("literal 16 stays; a share that collapses means the walk length should derive from the")
    print("ring capacity like everything else in this lane.")
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
