#!/usr/bin/env python3
"""The decision table for owner_cell.py, with its acceptance rule applied rather than described.

Two things this report will not do. It will not read a rate out of an unsaturated cell -- the first
run of this experiment drew 10.8 of 16 cores and reported a null that was the load generator's
number -- and it will not call a null a null without saying what the CPU-per-work column did, which
is the signal that survives when the rate cannot resolve.

    owner_cell_report.py <csv>
"""
import csv, os, statistics as st, sys

rows = [r for r in csv.DictReader(open(sys.argv[1])) if r['arm'] != 'LADDER']
ladder = [r for r in csv.DictReader(open(sys.argv[1])) if r['arm'] == 'LADDER']
NUM = ('rate', 'p50', 'p99', 'cmds', 'instr', 'cycles', 'fills', 'hits', 'demoted',
       'fallbacks', 'srv_cores', 'wall', 'mux')
for r in rows + ladder:
    for k in NUM:
        r[k] = float(r[k])
    for k in ('srv_cpus', 'threads', 'conns'):
        r[k] = float(r.get(k) or 0)
    r['instr_op'] = r['instr'] / r['cmds'] if r['cmds'] else float('nan')
    r['cyc_op'] = r['cycles'] / r['cmds'] if r['cmds'] else float('nan')
    r['fills_op'] = r['fills'] / r['cmds'] if r['cmds'] else float('nan')
    r['ipc'] = r['instr'] / r['cycles'] if r['cycles'] else float('nan')
    # CPU PER UNIT WORK -- core-seconds per million operations. This is the column that still means
    # something when the rate is somebody else's limit, because it divides what the server spent by
    # what the server did rather than by how long the wall clock ran.
    r['cpu_per_mop'] = r['srv_cores'] / (r['rate'] / 1e6) if r['rate'] else float('nan')
    r['idle'] = 1.0 - r['srv_cores'] / r['srv_cpus'] if r['srv_cpus'] else float('nan')
    tot = r['hits'] + r['fallbacks']
    r['local_pct'] = 100.0 * r['hits'] / tot if tot else float('nan')

SHAPES = []
for r in rows:
    if r['shape'] not in SHAPES:
        SHAPES.append(r['shape'])
ARMS = ['RL0', 'PRE', 'POST']
LBL = {'1:1': '1:1 alternating   (ring never fills)',
       '5:5': '5:5 blocked       (~17 live, just over)',
       '10:10': '10:10 blocked     (~22 live, firmly over)'}


def med(shape, arm, f):
    v = [r[f] for r in rows if r['shape'] == shape and r['arm'] == arm and r[f] == r[f]]
    return st.median(v) if v else float('nan')


def spread(shape, arm, f):
    v = [r[f] for r in rows if r['shape'] == shape and r['arm'] == arm and r[f] == r[f]]
    m = st.median(v) if v else 0
    return 100.0 * (max(v) - min(v)) / m if v and m else float('nan')


if ladder:
    print('LOAD LADDER (POST arm, 10:10) -- where the generator stopped being the limit')
    h = f"{'threads x conns':>18}{'total conns':>13}{'M ops/s':>10}{'gain':>9}{'srv cores':>11}{'idle':>8}"
    print(h); print('-' * len(h))
    prev = None
    for r in ladder:
        t, c = int(r['threads']), int(r['conns'])
        gain = (r['rate'] - prev) / prev * 100 if prev else float('nan')
        print(f"{f'{t} x {c // t}':>18}{c:>13}{r['rate']/1e6:>10.3f}"
              f"{(f'{gain:+.1f}%' if gain == gain else '   --'):>9}"
              f"{r['srv_cores']:>10.2f}/{int(r['srv_cpus'])}{r['idle']*100:>7.1f}%")
        prev = r['rate']
    print()

geom = os.path.join(os.path.dirname(os.path.abspath(sys.argv[1])), 'geometry.txt')
SAT = None
if os.path.exists(geom):
    for line in open(geom):
        if line.startswith('saturated='):
            SAT = line.strip().split('=', 1)[1] == 'yes'
if SAT is None:
    SAT = all(med(s, a, 'idle') < 0.02 for s in SHAPES for a in ARMS
              if med(s, a, 'idle') == med(s, a, 'idle'))

hdr = (f"{'shape':<42}{'arm':<6}{'M ops/s':>9}{'spread':>8}{'cpu/Mop':>9}{'srv cores':>11}"
       f"{'idle':>7}{'instr/op':>10}{'IPC':>7}{'p99 ms':>9}{'local %':>9}{'demoted':>14}")
print(hdr); print('-' * len(hdr))
for s in SHAPES:
    for a in ARMS:
        if not any(r['shape'] == s and r['arm'] == a for r in rows):
            continue
        print(f"{LBL.get(s, s):<42}{a:<6}{med(s,a,'rate')/1e6:>9.3f}{spread(s,a,'rate'):>7.1f}%"
              f"{med(s,a,'cpu_per_mop'):>9.3f}{med(s,a,'srv_cores'):>11.2f}"
              f"{med(s,a,'idle')*100:>6.1f}%{med(s,a,'instr_op'):>10.0f}{med(s,a,'ipc'):>7.3f}"
              f"{med(s,a,'p99'):>9.2f}{med(s,a,'local_pct'):>8.1f}%{med(s,a,'demoted'):>14,.0f}")

    def d(x, y, f):
        p, q = med(s, x, f), med(s, y, f)
        return (q - p) / p * 100.0 if p and p == p else float('nan')
    print(f"{'':<42}{'':6}rate  POST/PRE {d('PRE','POST','rate'):+6.2f}%   POST/RL0 "
          f"{d('RL0','POST','rate'):+6.2f}%   PRE/RL0 {d('RL0','PRE','rate'):+6.2f}%")
    print(f"{'':<42}{'':6}cpu   POST/PRE {d('PRE','POST','cpu_per_mop'):+6.2f}%   POST/RL0 "
          f"{d('RL0','POST','cpu_per_mop'):+6.2f}%   PRE/RL0 "
          f"{d('RL0','PRE','cpu_per_mop'):+6.2f}%   (lower is better)")
    print()

print('=' * 118)
print('MECHANISM -- must have fired, or the cell says nothing about this lane')
print('=' * 118)
ok_mech = True
for s in SHAPES:
    dp, dq = med(s, 'PRE', 'demoted'), med(s, 'POST', 'demoted')
    if s == '1:1':
        good, verdict = dp < 50_000, ('as expected: the ring never fills here, so this shape is the '
                                      'no-op control')
    else:
        good = dp > 100_000 and dq < dp * 0.05
        verdict = ('PRE overflows and POST does not -- the fix fired' if good else
                   'THE FIX DID NOT FIRE: PRE should demote millions here. Hundreds means the '
                   'generator emitted an alternating shape, not a blocked one')
    ok_mech &= good
    print(f"  {s:<7} PRE demoted {dp:>12,.0f}   POST demoted {dq:>12,.0f}   {verdict}")

print()
print('=' * 118)
print('ACCEPTANCE')
print('=' * 118)
if not SAT:
    idl = max((med(s, a, 'idle') for s in SHAPES for a in ARMS
               if med(s, a, 'idle') == med(s, a, 'idle')), default=float('nan'))
    print(f'  NOT SATURATED -- up to {idl*100:.1f}% of the server\'s cores were idle. Every rate here')
    print('  is the load generator\'s number and no rate comparison may be read from this run.')
    print('  The CPU-per-work column below is still valid: it divides what the server spent by what')
    print('  the server did, not by how long the wall clock ran.')
    print()

lines = []
for s in SHAPES:
    if s == '1:1':
        gap = med(s, 'POST', 'rate') / med(s, 'PRE', 'rate') - 1
        lines.append(('GUARD  ', s, abs(gap) < 0.03, SAT,
                      f'POST vs PRE {gap*100:+.2f}% (must be flat: the ring never fills here)'))
        continue
    lines.append(('PRIMARY', s, med(s, 'POST', 'rate') >= med(s, 'RL0', 'rate'), SAT,
                  f"rate POST {med(s,'POST','rate')/1e6:.3f}M vs RL0 {med(s,'RL0','rate')/1e6:.3f}M "
                  f"({(med(s,'POST','rate')/med(s,'RL0','rate')-1)*100:+.2f}%) -- arming must no "
                  f"longer lose to not arming"))
    lines.append(('SECOND ', s, med(s, 'POST', 'rate') > med(s, 'PRE', 'rate'), SAT,
                  f"rate POST vs PRE {(med(s,'POST','rate')/med(s,'PRE','rate')-1)*100:+.2f}% -- the "
                  f"sized ring must beat the ring that gives up"))
    lines.append(('EFFIC  ', s, med(s, 'POST', 'cpu_per_mop') < med(s, 'PRE', 'cpu_per_mop'), True,
                  f"cpu/Mop POST {med(s,'POST','cpu_per_mop'):.3f} vs PRE "
                  f"{med(s,'PRE','cpu_per_mop'):.3f} "
                  f"({(med(s,'POST','cpu_per_mop')/med(s,'PRE','cpu_per_mop')-1)*100:+.2f}%) -- "
                  f"valid saturated or not"))
for kind, s, good, valid, text in lines:
    mark = ('PASS' if good else 'FAIL') if valid else 'n/a '
    print(f"  [{mark}] {kind} {s:<7} {text}")

print()
blocked = [s for s in SHAPES if s != '1:1']
rate_ok = all(g for k, s, g, v, _ in lines if v and k.strip() in ('PRIMARY', 'SECOND'))
guard_ok = all(g for k, s, g, v, _ in lines if k.strip() == 'GUARD')
effic_ok = all(g for k, s, g, v, _ in lines if k.strip() == 'EFFIC')
if not ok_mech:
    print('VERDICT: INCONCLUSIVE -- the mechanism did not fire. Fix the shape before reading rates.')
elif SAT and rate_ok and guard_ok:
    print('VERDICT: MERGE -- a THROUGHPUT win. POST beats both PRE and the unarmed line in the')
    print('regime the fix targets, and is flat where the ring never fills.')
elif SAT and effic_ok:
    print('VERDICT: EFFICIENCY CHANGE, NOT A THROUGHPUT ONE. Saturated, the rate does not separate,')
    print('but POST does the same work for less CPU. Merge it as an efficiency change or not at all;')
    print('do not claim a throughput win for it.')
elif not SAT and effic_ok:
    print('VERDICT: NOT PROVEN ON RATE (unsaturated), but the CPU-per-work edge is real and is the')
    print('only claim this run supports. Re-run saturated before any throughput claim.')
else:
    print('VERDICT: SHELVE STANDS on this geometry. Failed: ' +
          ', '.join(f'{k.strip()} {s}' for k, s, g, v, _ in lines if v and not g))
