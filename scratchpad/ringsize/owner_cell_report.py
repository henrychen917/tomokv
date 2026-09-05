#!/usr/bin/env python3
"""The decision table for owner_cell.py, with its acceptance rule applied rather than described.

    owner_cell_report.py <csv>
"""
import csv, statistics as st, sys

rows = list(csv.DictReader(open(sys.argv[1])))
for r in rows:
    for k in ('rate', 'p50', 'p99', 'cmds', 'instr', 'cycles', 'fills', 'hits', 'demoted',
              'fallbacks', 'srv_cores', 'wall', 'mux'):
        r[k] = float(r[k])
    r['instr_op'] = r['instr'] / r['cmds'] if r['cmds'] else float('nan')
    r['cyc_op'] = r['cycles'] / r['cmds'] if r['cmds'] else float('nan')
    r['fills_op'] = r['fills'] / r['cmds'] if r['cmds'] else float('nan')
    r['ipc'] = r['instr'] / r['cycles'] if r['cycles'] else float('nan')
    tot = r['hits'] + r['fallbacks']
    r['local_pct'] = 100.0 * r['hits'] / tot if tot else float('nan')

SHAPES = [s for s in ('1:1', '5:5', '10:10') if any(r['shape'] == s for r in rows)]
ARMS = ['RL0', 'PRE', 'POST']
LBL = {'1:1': '1:1 alternating  (ring never fills)',
       '5:5': '5:5 blocked      (~17 live, just over)',
       '10:10': '10:10 blocked    (~22 live, firmly over)'}


def med(shape, arm, f):
    v = [r[f] for r in rows if r['shape'] == shape and r['arm'] == arm and r[f] == r[f]]
    return st.median(v) if v else float('nan')


def spread(shape, arm, f):
    v = [r[f] for r in rows if r['shape'] == shape and r['arm'] == arm and r[f] == r[f]]
    m = st.median(v) if v else 0
    return 100.0 * (max(v) - min(v)) / m if v and m else float('nan')


hdr = (f"{'shape':<40}{'arm':<6}{'M ops/s':>9}{'spread':>8}{'instr/op':>10}{'cyc/op':>9}"
       f"{'IPC':>7}{'fills/op':>10}{'p99 ms':>9}{'local %':>9}{'demoted':>14}{'srv cores':>11}")
print(hdr); print('-' * len(hdr))
for s in SHAPES:
    for a in ARMS:
        if not any(r['shape'] == s and r['arm'] == a for r in rows):
            continue
        print(f"{LBL.get(s, s):<40}{a:<6}{med(s,a,'rate')/1e6:>9.3f}{spread(s,a,'rate'):>7.1f}%"
              f"{med(s,a,'instr_op'):>10.0f}{med(s,a,'cyc_op'):>9.0f}{med(s,a,'ipc'):>7.3f}"
              f"{med(s,a,'fills_op'):>10.2f}{med(s,a,'p99'):>9.2f}{med(s,a,'local_pct'):>8.1f}%"
              f"{med(s,a,'demoted'):>14,.0f}{med(s,a,'srv_cores'):>11.2f}")
    def d(x, y, f='rate'):
        p, q = med(s, x, f), med(s, y, f)
        return (q - p) / p * 100.0 if p and p == p else float('nan')
    print(f"{'':<40}{'':6}POST vs PRE {d('PRE','POST'):+7.2f}%     "
          f"POST vs RL0 {d('RL0','POST'):+7.2f}%     PRE vs RL0 {d('RL0','PRE'):+7.2f}%")
    print()

print('=' * 110)
print('MECHANISM -- must have fired, or the cell says nothing about this lane')
print('=' * 110)
ok_mech = True
for s in SHAPES:
    dp, dq = med(s, 'PRE', 'demoted'), med(s, 'POST', 'demoted')
    if s == '1:1':
        verdict = ('as expected: the ring never fills here, so neither arm demotes and this shape'
                   ' is the no-op control')
        good = dp < 50_000
    else:
        good = dp > 100_000 and dq < dp * 0.05
        verdict = ('PRE overflows and POST does not -- the fix fired' if good else
                   'THE FIX DID NOT FIRE: check that memtier emitted a BLOCKED shape (PRE should '
                   'demote millions here; hundreds means the ratio was reduced to alternating)')
    ok_mech &= good
    print(f"  {s:<7} PRE demoted {dp:>12,.0f}   POST demoted {dq:>12,.0f}   {verdict}")

print()
print('=' * 110)
print('ACCEPTANCE')
print('=' * 110)
print('  RL0 is the ordinary owner-task path measured FROM THE SAME TREE, which is the line the')
print('  armed arms have to clear. The t9final read-local-0 number is a different tree and is not')
print('  the comparator.')
print()
lines = []
for s in SHAPES:
    if s == '1:1':
        gap = med(s, 'POST', 'rate') / med(s, 'PRE', 'rate') - 1
        lines.append(('GUARD  ', s, abs(gap) < 0.03,
                      f'POST vs PRE {gap*100:+.2f}% (must be flat: the ring never fills here)'))
    else:
        primary = med(s, 'POST', 'rate') >= med(s, 'RL0', 'rate')
        lines.append(('PRIMARY', s, primary,
                      f"POST {med(s,'POST','rate')/1e6:.3f}M vs RL0 {med(s,'RL0','rate')/1e6:.3f}M "
                      f"({(med(s,'POST','rate')/med(s,'RL0','rate')-1)*100:+.2f}%) -- arming must "
                      f"no longer lose to not arming"))
        second = med(s, 'POST', 'rate') > med(s, 'PRE', 'rate')
        lines.append(('SECOND ', s, second,
                      f"POST vs PRE {(med(s,'POST','rate')/med(s,'PRE','rate')-1)*100:+.2f}% -- the "
                      f"ring fix must beat the ring that gives up"))
for kind, s, good, text in lines:
    print(f"  [{'PASS' if good else 'FAIL'}] {kind} {s:<7} {text}")
print()
if not ok_mech:
    print('VERDICT: INCONCLUSIVE -- the mechanism did not fire; fix the shape before reading rates.')
elif all(g for _, _, g, _ in lines):
    print('VERDICT: MERGE. The change wins in the regime it targets and is flat where it does')
    print('nothing. On this geometry the shelve verdict is overturned.')
else:
    failed = [f'{k.strip()} {s}' for k, s, g, _ in lines if not g]
    print('VERDICT: SHELVE STANDS on this geometry. Failed: ' + ', '.join(failed))
