"""Item 4 BLOCK-WAKE-RENAME-SORTSTORE residual.

Per attempt: fresh source s (built with the right type) and fresh target k. Waiter W blocks on
k (BLPOP for lists, BZPOPMIN for zsets, XREAD BLOCK 0 STREAMS k 0-0 for streams) and is PARKED
(INFO). Then ONE creator command creates k from s.
HIT = waiter parked + the creator created k (COPY 1, RESTORE OK, *STORE > 0, RENAME OK, ...).
DEFECT = a hit whose waiter is not served within --grace (Redis signals readiness at key
creation, so it serves at once).
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from common import base_args, boot, geometry, Log  # noqa: E402
import srv  # noqa: E402
from resp import Err, wait_blocked, blocked_clients, show  # noqa: E402

GEO = [13.361389, 38.115556, 'Palermo', 15.087269, 37.502669, 'Catania']

CREATORS = {
    # name: (type, creator argv builder(s, k, payload), created predicate)
    'COPY-list': ('list', lambda s, k, pl: ['COPY', s, k]),
    'RESTORE-list': ('list', lambda s, k, pl: ['RESTORE', k, 0, pl]),
    'RENAME-list(ctl)': ('list', lambda s, k, pl: ['RENAME', s, k]),
    'SORTSTORE-list(ctl)': ('list', lambda s, k, pl: ['SORT', s, 'ALPHA', 'STORE', k]),
    'LMOVE-list(ctl)': ('list', lambda s, k, pl: ['LMOVE', s, k, 'LEFT', 'RIGHT']),
    'COPY-zset': ('zset', lambda s, k, pl: ['COPY', s, k]),
    'RESTORE-zset': ('zset', lambda s, k, pl: ['RESTORE', k, 0, pl]),
    'ZUNIONSTORE': ('zset', lambda s, k, pl: ['ZUNIONSTORE', k, 1, s]),
    'ZINTERSTORE': ('zset', lambda s, k, pl: ['ZINTERSTORE', k, 1, s]),
    'ZDIFFSTORE': ('zset', lambda s, k, pl: ['ZDIFFSTORE', k, 1, s]),
    'ZRANGESTORE': ('zset', lambda s, k, pl: ['ZRANGESTORE', k, s, 0, -1]),
    'GEOSEARCHSTORE': ('geo', lambda s, k, pl: ['GEOSEARCHSTORE', k, s, 'FROMLONLAT', 15, 37,
                                               'BYRADIUS', 400, 'km', 'ASC']),
    'RENAME-zset(ctl)': ('zset', lambda s, k, pl: ['RENAME', s, k]),
    'COPY-stream': ('stream', lambda s, k, pl: ['COPY', s, k]),
    'RESTORE-stream': ('stream', lambda s, k, pl: ['RESTORE', k, 0, pl]),
    'RENAME-stream(ctl)': ('stream', lambda s, k, pl: ['RENAME', s, k]),
}


def created(reply):
    if isinstance(reply, Err):
        return False
    if reply == 'OK':
        return True
    if isinstance(reply, int):
        return reply > 0
    if isinstance(reply, bytes):
        return True  # LMOVE returns the moved element
    return False


p = base_args('item 4 creators')
p.add_argument('--creators', default=','.join(CREATORS))
p.add_argument('--max-attempts', type=int, default=220)
p.add_argument('--confirm', type=int, default=8, help='stop a creator after N defects')
p.add_argument('--placement', choices=['random', 'same-shard', 'cross-owner'], default='random')
p.add_argument('--grace', type=float, default=1.0)
p.add_argument('--long-wait', type=float, default=5.0)
p.add_argument('--max-nonhit-streak', type=int, default=5)
a = p.parse_args()

s = boot(a, tag='item4-%s' % a.server)
log = Log('item4', a, a.placement)
c, w, x = s.conn(), s.conn(), s.conn()
log.write(event='boot', geometry=geometry(a), version=s.version, bootline=s.bootline,
          placement=a.placement)
print('geometry:', geometry(a), '|', s.bootline, '| placement', a.placement)
run = '%x' % (int(time.time() * 1000) & 0xffffff)
results = {}

for name in a.creators.split(','):
    typ, build = CREATORS[name]
    st = dict(attempts=0, parked=0, hits=0, defects=0, served=0, served_after_long=0,
              served_after_plain_push=0, long_checked=0, creator_errors={})
    streak = 0
    for i in range(a.max_attempts):
        st['attempts'] += 1
        base = 'c4:%s:%s:%d' % (run, name.split('(')[0], i)
        if a.server == 'tomokv' and a.placement != 'random':
            rel = {'same-shard': 'shard_eq', 'cross-owner': 'owner_ne'}[a.placement]
            names, placed = srv.pick_keys(c, base, [{'name': 's'}, {'name': 'k', rel: 's'}])
            src, k = names['s'], names['k']
        else:
            src, k = base + ':s', base + ':k'
            placed = srv.shards_of(c, src, k) if a.server == 'tomokv' else None
        if typ == 'list':
            c.cmd('RPUSH', src, 'a', 'b')
        elif typ == 'zset':
            c.cmd('ZADD', src, 1, 'a', 2, 'b')
        elif typ == 'geo':
            c.cmd('GEOADD', src, *GEO)
        else:
            c.cmd('XADD', src, '1-1', 'f', 'v')
        payload = c.cmd('DUMP', src) if name.startswith('RESTORE') else None
        if typ == 'list':
            w.send('BLPOP', k, 0)
        elif typ in ('zset', 'geo'):
            w.send('BZPOPMIN', k, 0)
        else:
            w.send('XREAD', 'BLOCK', 0, 'STREAMS', k, '0-0')
        if not wait_blocked(c, 1):
            log.write(creator=name, i=i, parked=False)
            w.close(); w = s.conn(); continue
        st['parked'] += 1
        argv = build(src, k, payload)
        r = x.cmd(*argv)
        hit = created(r)
        rec = dict(creator=name, i=i, key=k, placement=placed, creator_reply=show(r), hit=hit)
        if hit:
            st['hits'] += 1
            streak = 0
        else:
            streak += 1
            st['creator_errors'][show(r)] = st['creator_errors'].get(show(r), 0) + 1
        served, wr = w.try_read(a.grace)
        rec['served_within_grace'] = served
        if served:
            st['served'] += 1
            rec['waiter_reply'] = show(wr)
        else:
            if hit:
                st['defects'] += 1
            rec['type_k_while_blocked'] = show(c.cmd('TYPE', k))
            rec['blocked_clients'] = blocked_clients(c)
            if st['defects'] == 1:
                st['long_checked'] += 1
                ok2, wr2 = w.try_read(a.long_wait)
                rec['served_after_long_wait'] = ok2
                if ok2:
                    st['served_after_long'] += 1
                    served = True
                    rec['waiter_reply'] = show(wr2)
            if not served:
                if typ == 'list':
                    rec['plain_push'] = show(c.cmd('RPUSH', k, 'wake'))
                elif typ in ('zset', 'geo'):
                    rec['plain_push'] = show(c.cmd('ZADD', k, 0, 'wake'))
                else:
                    rec['plain_push'] = show(c.cmd('XADD', k, '*', 'wake', '1'))
                ok3, wr3 = w.try_read(2)
                rec['served_after_plain_push'] = ok3
                if ok3:
                    st['served_after_plain_push'] += 1
                    rec['waiter_reply'] = show(wr3)
                else:
                    w.close(); w = s.conn(); wait_blocked(c, 0)
        log.write(**rec)
        c.cmd('DEL', src, k)
        wait_blocked(c, 0, timeout=2)
        if st['defects'] >= a.confirm:
            break
        if st['hits'] >= 200 and st['defects'] == 0:
            break
        if streak >= a.max_nonhit_streak:
            break
    results[name] = st
    verdict = 'CONFIRMED' if st['defects'] else ('NOT REPRODUCED' if st['hits'] >= 200 else
               ('CREATOR-FAILED' if st['creator_errors'] and not st['hits'] else 'INSUFFICIENT'))
    print('%-20s %-15s hits=%d defects=%d served=%d after_long=%d/%d after_plain_push=%d %s' % (
        name, verdict, st['hits'], st['defects'], st['served'], st['served_after_long'],
        st['long_checked'], st['served_after_plain_push'],
        ('errors=%s' % st['creator_errors']) if st['creator_errors'] else ''))
    log.write(event='creator-summary', creator=name, verdict=verdict, **st)

log.write(event='summary', geometry=geometry(a), results=results)
print('log:', log.path)
log.close()
for y in (c, w, x):
    y.close()
s.stop()
