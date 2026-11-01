"""Item 1, MVCC variant WITHOUT debug hooks (atomic 1, read-local 0).

Per attempt: fresh k; p on k's shard; q on another owner. Waiter W parked on k (INFO).
G runs one atomic cross-owner MSET p q (a concurrent transaction on k's shard), E pushes to k
with a single-key EVAL, and E then reads INFO atomic_pending_entries in the same pipeline.
HIT = pending >= 1 after the EVAL reply (records only shrink after the MSET commit, so they
were live when the EVAL ran). DEFECT = waiter not served within --grace.
--order after: EVAL sent right after MSET's reply. --order race: MSET and EVAL sent
back-to-back on two connections without waiting.
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from common import base_args, boot, geometry, Log  # noqa: E402
import srv  # noqa: E402
from resp import wait_blocked, blocked_clients, show  # noqa: E402

SCRIPT = "redis.call('RPUSH', KEYS[1], ARGV[1]); return redis.call('LLEN', KEYS[1])"
p = base_args('item 1 natural MVCC variant')
p.add_argument('--order', choices=['after', 'race'], default='after')
p.add_argument('--grace', type=float, default=1.0)
p.add_argument('--long-wait', type=float, default=10.0)
p.add_argument('--stop-after-defects', type=int, default=10)
a = p.parse_args()
assert a.server == 'tomokv' and a.atomic == 1

s = boot(a, tag='item1nat-%s' % a.order)
log = Log('item1nat', a, a.order)
c, w, e, g = s.conn(), s.conn(), s.conn(), s.conn()
log.write(event='boot', geometry=geometry(a), version=s.version, bootline=s.bootline, order=a.order)
print('geometry:', geometry(a), '|', s.bootline)
run = '%x' % (int(time.time() * 1000) & 0xffffff)
st = dict(attempts=0, parked=0, hits=0, hit_defects=0, nonhit_defects=0, served=0,
          served_after_long=0)


def pend_from(reply):
    for line in reply.decode().split('\r\n'):
        if line.startswith('atomic_pending_entries:'):
            return int(line.split(':')[1])
    return -1


for i in range(a.attempts):
    st['attempts'] += 1
    names, placed = srv.pick_keys(c, 'n1:%s:%d' % (run, i),
                                  [{'name': 'k'}, {'name': 'p', 'shard_eq': 'k'},
                                   {'name': 'q', 'owner_ne': 'k'}])
    k, pk, qk = names['k'], names['p'], names['q']
    c.cmd('SET', pk, 'old'); c.cmd('SET', qk, 'old')
    w.send('BLPOP', k, 0)
    if not wait_blocked(c, 1):
        log.write(i=i, parked=False); w.close(); w = s.conn(); continue
    st['parked'] += 1
    if a.order == 'after':
        mset = g.cmd('MSET', pk, 'new%d' % i, qk, 'new%d' % i)
        ev, info = e.pipeline([['EVAL', SCRIPT, 1, k, 'x'], ['INFO', 'stats']])
    else:
        g.send('MSET', pk, 'new%d' % i, qk, 'new%d' % i)
        ev, info = e.pipeline([['EVAL', SCRIPT, 1, k, 'x'], ['INFO', 'stats']])
        mset = g.read()
    pending = pend_from(info)
    hit = pending >= 1 and isinstance(ev, int)
    served, wr = w.try_read(a.grace)
    rec = dict(i=i, placement=placed, mset=show(mset), eval=show(ev), pending_after_eval=pending,
               hit=hit, served_within_grace=served)
    if hit:
        st['hits'] += 1
    if served:
        st['served'] += 1
        rec['waiter_reply'] = show(wr)
    else:
        if hit:
            st['hit_defects'] += 1
        else:
            st['nonhit_defects'] += 1
        rec['llen_while_blocked'] = show(c.cmd('LLEN', k))
        rec['blocked_clients'] = blocked_clients(c)
        served2, wr2 = w.try_read(a.long_wait)
        rec['served_after_long_wait'] = served2
        if served2:
            st['served_after_long'] += 1
        else:
            rec['llen_after_long_wait'] = show(c.cmd('LLEN', k))
            rec['plain_rpush'] = show(c.cmd('RPUSH', k, 'wake'))
            ok, wr3 = w.try_read(2)
            rec['served_after_plain_push'] = ok
            if not ok:
                w.close(); w = s.conn(); wait_blocked(c, 0)
    log.write(**rec)
    c.cmd('DEL', k, pk, qk)
    wait_blocked(c, 0, timeout=2)
    if st['hit_defects'] + st['nonhit_defects'] >= a.stop_after_defects:
        break

st['geometry'] = geometry(a); st['order'] = a.order
log.write(event='summary', **st)
print('SUMMARY', st)
print('log:', log.path)
log.close()
for x in (c, w, e, g):
    x.close()
s.stop()
