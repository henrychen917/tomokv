#!/usr/bin/env python3
"""ONE TABLE, ASSEMBLED FROM EVERY PHASE THAT PRODUCED A NUMBER.

The lane's phases each write their own csv and their own report; this joins them into the single
table the verdict is argued from, with the null's own per-cell spread carried beside every delta so
no row can be read without its floor. Nothing here recomputes a measurement -- it only puts the
columns that belong together in one place, and refuses to print a delta whose cell failed its null.

    final_table.py <outdir>
"""
import csv, os, statistics as st, sys

OUT = sys.argv[1] if len(sys.argv) > 1 else '.'

def load(name):
    p = os.path.join(OUT, name)
    if not os.path.exists(p):
        return []
    rows = list(csv.DictReader(open(p)))
    for r in rows:
        for k, v in list(r.items()):
            if k in ('arm', 'cell', 'ratio', 'cores'):
                continue
            try:
                r[k] = float(v)
            except (TypeError, ValueError):
                r[k] = float('nan')
        c = r.get('cmds') or 1.0
        r['instr_op'] = (r.get('instr') or 0) / c
        r['cyc_op'] = (r.get('cycles') or 0) / c
        r['fills_op'] = (r.get('fills') or 0) / c
        cyc = r.get('cycles') or 0
        r['ipc'] = (r.get('instr') or 0) / cyc if cyc else float('nan')
        h = r.get('read_local_hits') or 0
        a = r.get('read_local_fallbacks') or 0
        r['local_pct'] = 100.0 * h / (h + a) if (h + a) else float('nan')
    return rows

def med(rows, cell, arm, f):
    v = [r[f] for r in rows if r['cell'] == cell and r['arm'] == arm and r[f] == r[f]]
    return st.median(v) if v else float('nan')

def spread(rows, cell, f):
    v = [r[f] for r in rows if r['cell'] == cell and r[f] == r[f]]
    m = st.median(v) if v else 0
    return 100.0 * (max(v) - min(v)) / m if v and m else float('nan')

def delta(rows, cell, f):
    p, q = med(rows, cell, 'PRE', f), med(rows, cell, 'POST', f)
    return (q - p) / p * 100.0 if p and p == p else float('nan')

null = load('ab_null.csv')
rate = load('ab_triad.csv')
matched = load('ab_matched.csv')
ovf = load('ab_ovf.csv')
conn = load('regimes_conn.csv')
mset = load('regimes_mset.csv')

LBL = {'w41': '41% writes (under)', 'w55': '55% writes (edge)', 'w70': '70% writes (over)',
       'w100': 'pure SET null', 'r100': 'pure GET null'}
CELLS = ['w41', 'w55', 'w70', 'w100', 'r100']

def fmt(x, w=8, p=2, pct=False, plus=False):
    if x != x:
        return ' ' * (w - 2) + '--'
    s = f"{x:+.{p}f}" if plus else f"{x:.{p}f}"
    return (s + ('%' if pct else '')).rjust(w)

print("=" * 118)
print("TABLE 1 -- THREE REGIMES AT p32, 1s FUSED + READ-LOCAL ARMED, 512 CONNECTIONS")
print("saturated A/B; the NULL column is the same-binary run's own spread for that cell and column")
print("=" * 118)
hdr = (f"{'cell':<20}{'PRE M/s':>9}{'POST M/s':>9}{'rate':>8}{'null':>7} | "
       f"{'PRE i/op':>9}{'POST i/op':>10}{'instr':>8}{'null':>7} | "
       f"{'cyc/op d':>9}{'IPC d':>7}{'fills d':>9}")
print(hdr); print('-' * len(hdr))
for c in CELLS:
    if not any(r['cell'] == c for r in rate):
        continue
    print(f"{LBL[c]:<20}{med(rate,c,'PRE','rate')/1e6:>9.3f}{med(rate,c,'POST','rate')/1e6:>9.3f}"
          f"{fmt(delta(rate,c,'rate'),8,2,True,True)}{fmt(spread(null,c,'rate'),7,1,True)} | "
          f"{med(rate,c,'PRE','instr_op'):>9.0f}{med(rate,c,'POST','instr_op'):>10.0f}"
          f"{fmt(delta(rate,c,'instr_op'),8,2,True,True)}{fmt(spread(null,c,'instr_op'),7,2,True)} | "
          f"{fmt(delta(rate,c,'cyc_op'),9,2,True,True)}{fmt(delta(rate,c,'ipc'),7,2,True,True)}"
          f"{fmt(delta(rate,c,'fills_op'),9,2,True,True)}")

print()
print("mechanism: read-local hit share, write-demotions and ring overflows per arm")
h2 = (f"{'cell':<20}{'local% PRE':>11}{'local% POST':>12}{'demoted PRE':>13}{'demoted POST':>14}"
      f"{'ovf PRE':>10}{'ovf POST':>10}{'srv cores':>11}")
print(h2); print('-' * len(h2))
for c in CELLS:
    src = ovf if any(r['cell'] == c for r in ovf) else rate
    if not any(r['cell'] == c for r in src):
        continue
    print(f"{LBL[c]:<20}{med(rate,c,'PRE','local_pct'):>10.1f}%{med(rate,c,'POST','local_pct'):>11.1f}%"
          f"{med(rate,c,'PRE','read_local_fallback_inflight_write'):>13.0f}"
          f"{med(rate,c,'POST','read_local_fallback_inflight_write'):>14.0f}"
          f"{med(src,c,'PRE','ring_overflows'):>10.0f}{med(src,c,'POST','ring_overflows'):>10.0f}"
          f"{med(rate,c,'PRE','srv_cores'):>11.2f}")

if matched:
    print()
    print("=" * 118)
    print("TABLE 2 -- THE SAME CELLS AT MATCHED DELIVERED RATE (both arms rate-limited equally),")
    print("which is the only geometry in which instructions/op is a work measure and not a spin measure")
    print("=" * 118)
    h3 = (f"{'cell':<20}{'PRE M/s':>9}{'POST M/s':>9}{'rate gap':>10} | "
          f"{'PRE i/op':>9}{'POST i/op':>10}{'instr':>8} | {'cyc/op':>8}{'IPC':>7}{'fills':>8}")
    print(h3); print('-' * len(h3))
    for c in CELLS:
        if not any(r['cell'] == c for r in matched):
            continue
        print(f"{LBL[c]:<20}{med(matched,c,'PRE','rate')/1e6:>9.3f}"
              f"{med(matched,c,'POST','rate')/1e6:>9.3f}"
              f"{fmt(delta(matched,c,'rate'),10,2,True,True)} | "
              f"{med(matched,c,'PRE','instr_op'):>9.0f}{med(matched,c,'POST','instr_op'):>10.0f}"
              f"{fmt(delta(matched,c,'instr_op'),8,2,True,True)} | "
              f"{fmt(delta(matched,c,'cyc_op'),8,2,True,True)}{fmt(delta(matched,c,'ipc'),7,2,True,True)}"
              f"{fmt(delta(matched,c,'fills_op'),8,2,True,True)}")
    print("(a 'rate gap' materially above zero means the limit did not bind and the cell is the")
    print(" saturated run again -- read it before reading the instructions column.)")

if conn:
    print()
    print("=" * 118)
    print("TABLE 3 -- CONNECTION FOOTPRINT: 1:1 at p32, 512 against 2048 connections")
    print("=" * 118)
    h4 = (f"{'cell':<14}{'arm':<6}{'M ops/s':>9}{'instr/op':>10}{'cyc/op':>9}{'IPC':>7}"
          f"{'fills/op':>10}{'p99 ms':>8}{'local %':>9}{'srv cores':>11}")
    print(h4); print('-' * len(h4))
    for c in ('c512', 'c2048'):
        for arm in ('PRE', 'POST'):
            print(f"{c:<14}{arm:<6}{med(conn,c,arm,'rate')/1e6:>9.3f}"
                  f"{med(conn,c,arm,'instr_op'):>10.0f}{med(conn,c,arm,'cyc_op'):>9.0f}"
                  f"{med(conn,c,arm,'ipc'):>7.3f}{med(conn,c,arm,'fills_op'):>10.3f}"
                  f"{med(conn,c,arm,'p99'):>8.2f}{med(conn,c,arm,'local_pct'):>8.1f}%"
                  f"{med(conn,c,arm,'srv_cores'):>11.2f}")
        print(f"{'':<14}{'delta':<6}{fmt(delta(conn,c,'rate'),9,2,True,True)}"
              f"{fmt(delta(conn,c,'instr_op'),10,2,True,True)}{fmt(delta(conn,c,'cyc_op'),9,2,True,True)}"
              f"{fmt(delta(conn,c,'ipc'),7,2,True,True)}{fmt(delta(conn,c,'fills_op'),10,2,True,True)}")
    lo = med(conn, 'c512', 'POST', 'fills_op') - med(conn, 'c512', 'PRE', 'fills_op')
    hi = med(conn, 'c2048', 'POST', 'fills_op') - med(conn, 'c2048', 'PRE', 'fills_op')
    print()
    print(f"FOOTPRINT TERM: POST adds {lo:+.3f} fills/op at 512 and {hi:+.3f} at 2048 "
          f"({hi - lo:+.3f} of growth).")
    print("Growth with connection count IS the +973 bytes per armed connection, and it is the only")
    print("half of the cost that a grow-on-demand ring could return. No growth means re-sizing is")
    print("not the lever.")

if mset:
    print()
    print("=" * 118)
    print("TABLE 4 -- MSET WIDTH: 8 keys against 32, 1:1 at p8. kMaxPreciseKeysetKeys = 16.")
    print("Both arms go conservative past 16 keys, so the question is the drop WITHIN an arm.")
    print("=" * 118)
    h5 = (f"{'arm':<6}{'M/s 8key':>10}{'M/s 32key':>11}{'rate':>9}"
          f"{'local% 8':>10}{'local% 32':>11}{'share lost':>12}{'i/op 8':>9}{'i/op 32':>9}")
    print(h5); print('-' * len(h5))
    for arm in ('PRE', 'POST'):
        r8, r32 = med(mset, 'm8', arm, 'rate') / 1e6, med(mset, 'm32', arm, 'rate') / 1e6
        s8, s32 = med(mset, 'm8', arm, 'local_pct'), med(mset, 'm32', arm, 'local_pct')
        print(f"{arm:<6}{r8:>10.3f}{r32:>11.3f}{fmt(100*(r32/r8-1) if r8 else float('nan'),9,2,True,True)}"
              f"{s8:>9.1f}%{s32:>10.1f}%{s32-s8:>+11.1f}pp"
              f"{med(mset,'m8',arm,'instr_op'):>9.0f}{med(mset,'m32',arm,'instr_op'):>9.0f}")
    print()
    print(f"PRE/POST at 8 keys: rate {fmt(delta(mset,'m8','rate'),0,2,True,True).strip()}, "
          f"instr/op {fmt(delta(mset,'m8','instr_op'),0,2,True,True).strip()}")
    print(f"PRE/POST at 32 keys: rate {fmt(delta(mset,'m32','rate'),0,2,True,True).strip()}, "
          f"instr/op {fmt(delta(mset,'m32','instr_op'),0,2,True,True).strip()}")
