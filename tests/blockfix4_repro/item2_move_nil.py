"""Item 2 BLOCK-MOVE-RESUME-NIL.

Per attempt: fresh src/dst; waiter W sends a timeout-0 move (BLMOVE LEFT RIGHT, BLMOVE RIGHT
LEFT or BRPOPLPUSH) and is PARKED (INFO blocked_clients == 1). Pusher P then writes
`RPUSH src x` + `LPOP src` in ONE sendall.
HIT = the LPOP returned x (it took the element before the waiter's move ran).
DEFECT = on a hit, the waiter answers a null bulk ($-1) although its timeout is 0.
Redis: the waiter is served inside RPUSH, so LPOP always answers nil (0 hits by design).
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from common import base_args, boot, geometry, Log  # noqa: E402
import srv  # noqa: E402
from resp import NIL_BULK, wait_blocked, blocked_clients, show  # noqa: E402

p = base_args('item 2 BLOCK-MOVE-RESUME-NIL')
p.add_argument('--placement', choices=['random', 'same-shard', 'cross-owner', 'same-owner'],
               default='random')
p.add_argument('--grace', type=float, default=1.0)
p.add_argument('--stop-after-defects', type=int, default=0)
p.add_argument('--thief', choices=['pipelined', 'other-client'], default='pipelined')
a = p.parse_args()
KINDS = [('BLMOVE', 'LEFT', 'RIGHT'), ('BLMOVE', 'RIGHT', 'LEFT'), ('BRPOPLPUSH',)]

s = boot(a, tag='item2-%s' % a.server)
log = Log('item2', a, '%s-%s' % (a.placement, a.thief))
c, w, pz, t = s.conn(), s.conn(), s.conn(), s.conn()
log.write(event='boot', geometry=geometry(a), version=s.version, bootline=s.bootline,
          placement=a.placement, thief=a.thief)
print('geometry:', geometry(a), '|', s.bootline, '| placement', a.placement, '| thief', a.thief)
run = '%x' % (int(time.time() * 1000) & 0xffffff)
st = dict(attempts=0, parked=0, hits=0, defects_nil=0, hit_waiter_still_blocked=0,
          hit_waiter_other=0, nonhit_served_x=0, nonhit_other=0)
spec = {'random': [{'name': 'src'}, {'name': 'dst'}],
        'same-shard': [{'name': 'src'}, {'name': 'dst', 'shard_eq': 'src'}],
        'cross-owner': [{'name': 'src'}, {'name': 'dst', 'owner_ne': 'src'}],
        'same-owner': [{'name': 'src'}, {'name': 'dst', 'owner_eq': 'src', 'shard_ne': 'src'}]}

for i in range(a.attempts):
    st['attempts'] += 1
    kind = KINDS[i % len(KINDS)]
    if a.server == 'tomokv':
        names, placed = srv.pick_keys(c, 'm2:%s:%d' % (run, i), spec[a.placement])
        src, dst = names['src'], names['dst']
    else:
        src, dst, placed = 'm2:%s:%d:src' % (run, i), 'm2:%s:%d:dst' % (run, i), None
    if kind[0] == 'BLMOVE':
        w.send('BLMOVE', src, dst, kind[1], kind[2], 0)
    else:
        w.send('BRPOPLPUSH', src, dst, 0)
    if not wait_blocked(c, 1):
        log.write(i=i, parked=False); w.close(); w = s.conn(); continue
    st['parked'] += 1
    if a.thief == 'pipelined':
        rp, lp = pz.pipeline([['RPUSH', src, 'x'], ['LPOP', src]])
    else:
        pz.send('RPUSH', src, 'x')
        t.send('LPOP', src)
        rp, lp = pz.read(), t.read()
    hit = lp == b'x'
    rec = dict(i=i, kind=' '.join(kind), placement=placed, rpush=show(rp), lpop=show(lp), hit=hit)
    served, wr = w.try_read(a.grace)
    rec['waiter_answered_within_grace'] = served
    rec['waiter_reply'] = show(wr) if served else None
    if hit:
        st['hits'] += 1
        if served and wr is NIL_BULK:
            st['defects_nil'] += 1
            rec['defect'] = 'timeout-0 move answered null bulk'
        elif not served:
            st['hit_waiter_still_blocked'] += 1
            rec['blocked_clients'] = blocked_clients(c)
            c.cmd('RPUSH', src, 'y')
            ok, wr2 = w.try_read(2)
            rec['after_second_push'] = show(wr2) if ok else 'still blocked'
            if not ok:
                w.close(); w = s.conn(); wait_blocked(c, 0)
        else:
            st['hit_waiter_other'] += 1
    else:
        if served and wr == b'x':
            st['nonhit_served_x'] += 1
        else:
            st['nonhit_other'] += 1
            if not served:
                c.cmd('RPUSH', src, 'y')
                ok, wr2 = w.try_read(2)
                rec['after_second_push'] = show(wr2) if ok else 'still blocked'
                if not ok:
                    w.close(); w = s.conn(); wait_blocked(c, 0)
    rec['dst_after'] = show(c.cmd('LRANGE', dst, 0, -1))
    log.write(**rec)
    c.cmd('DEL', src, dst)
    wait_blocked(c, 0, timeout=2)
    if a.stop_after_defects and st['defects_nil'] >= a.stop_after_defects:
        break

st['geometry'] = geometry(a); st['placement'] = a.placement; st['thief'] = a.thief
log.write(event='summary', **st)
print('SUMMARY', st)
print('log:', log.path)
log.close()
for x in (c, w, pz, t):
    x.close()
s.stop()
