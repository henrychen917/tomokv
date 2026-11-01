"""Item 1 SCRIPT-PUSH-NO-WAKE.

Per attempt: a fresh key k; waiter W sends BLPOP/BRPOP/BLMOVE k ... 0; admin C polls INFO
until blocked_clients == 1 (the waiter is PARKED); then a single-key script pushes to k.
HIT = waiter parked + script push executed (+ for --variant hold: MVCC records present on
k's shard, proved by INFO atomic_pending_entries >= 2 while DEBUG ATOMIC-COMMIT-HOLD holds a
cross-owner atomic MSET whose first key shares k's shard).
DEFECT = a hit whose waiter is not served within --grace seconds (Redis: always served).
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from common import base_args, boot, geometry, Log  # noqa: E402
import srv  # noqa: E402
from resp import Err, wait_blocked, blocked_clients, info_field, show  # noqa: E402

SCRIPT = "redis.call('RPUSH', KEYS[1], ARGV[1]); return redis.call('LLEN', KEYS[1])"
LIB = ("#!lua name=r1push\nredis.register_function('pushlen', function(keys, args) "
       "redis.call('RPUSH', keys[1], args[1]); return redis.call('LLEN', keys[1]) end)")

p = base_args('item 1 SCRIPT-PUSH-NO-WAKE')
p.add_argument('--variant', choices=['plain', 'hold'], default='plain')
p.add_argument('--pusher', choices=['eval', 'evalsha', 'fcall'], default='eval')
p.add_argument('--grace', type=float, default=1.0)
p.add_argument('--long-every', type=int, default=0)
p.add_argument('--long-wait', type=float, default=10.0)
p.add_argument('--kinds', default='BLPOP,BRPOP,BLMOVE')
a = p.parse_args()
kinds = a.kinds.split(',')

s = boot(a, tag='item1-%s-%s' % (a.server, a.variant))
log = Log('item1', a, '%s-%s' % (a.variant, a.pusher))
c, w, e, g = s.conn(), s.conn(), s.conn(), s.conn()
sha = None
if a.pusher == 'evalsha':
    sha = c.cmd('SCRIPT', 'LOAD', SCRIPT).decode()
if a.pusher == 'fcall':
    r = c.cmd('FUNCTION', 'LOAD', 'REPLACE', LIB)
    assert not isinstance(r, Err), r
atomic_cfg = c.cmd('CONFIG', 'GET', 'atomic') if a.server == 'tomokv' else None
log.write(event='boot', geometry=geometry(a), version=s.version, bootline=s.bootline,
          variant=a.variant, pusher=a.pusher, config_atomic=show(atomic_cfg) if atomic_cfg else None)
print('geometry:', geometry(a), '|', s.bootline, '| CONFIG GET atomic ->', show(atomic_cfg) if atomic_cfg else '-')

stats = dict(attempts=0, parked=0, hits=0, served=0, not_served=0, served_after_long=0,
             served_after_release=0, served_after_plain_push=0, still_stuck=0, mid_llen={})
run = '%x' % (int(time.time() * 1000) & 0xffffff)


def pending(conn):
    v = info_field(conn, 'stats', 'atomic_pending_entries')
    return int(v) if v is not None else -1


def push(conn, k):
    if a.pusher == 'eval':
        conn.send('EVAL', SCRIPT, 1, k, 'x')
    elif a.pusher == 'evalsha':
        conn.send('EVALSHA', sha, 1, k, 'x')
    else:
        conn.send('FCALL', 'pushlen', 1, k, 'x')


for i in range(a.attempts):
    kind = kinds[i % len(kinds)]
    stats['attempts'] += 1
    rec = dict(i=i, kind=kind)
    k, d = 's1:%s:%d:k' % (run, i), 's1:%s:%d:d' % (run, i)
    pk = qk = None
    if a.variant == 'hold':
        names, placed = srv.pick_keys(c, 's1:%s:%d' % (run, i),
                                      [{'name': 'k'}, {'name': 'p', 'shard_eq': 'k'},
                                       {'name': 'q', 'owner_ne': 'k'}])
        k, pk, qk = names['k'], names['p'], names['q']
        rec['placement'] = placed
        c.cmd('SET', pk, 'old')
        c.cmd('SET', qk, 'old')
    elif a.server == 'tomokv':
        rec['placement'] = srv.shards_of(c, k)
    if kind == 'BLPOP':
        w.send('BLPOP', k, 0)
    elif kind == 'BRPOP':
        w.send('BRPOP', k, 0)
    else:
        w.send('BLMOVE', k, d, 'LEFT', 'RIGHT', 0)
    parked = wait_blocked(c, 1)
    rec['parked'] = parked
    if not parked:
        rec['note'] = 'waiter never parked'
        log.write(**rec)
        w.close(); w = s.conn()
        continue
    stats['parked'] += 1
    installed = True
    if a.variant == 'hold':
        assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 1) == 'OK'
        g.send('MSET', pk, 'new', qk, 'new')
        t0 = time.monotonic()
        installed = False
        while time.monotonic() - t0 < 3:
            if pending(c) >= 2:
                installed = True
                break
            time.sleep(0.001)
        rec['pending_before_push'] = pending(c)
        rec['installed'] = installed
    push(e, k)
    got, ev = e.try_read(3.0)
    rec['push_reply'] = show(ev) if got else 'NO REPLY in 3s'
    if a.variant == 'hold':
        rec['pending_after_push'] = pending(c)
    hit = parked and installed and got and isinstance(ev, int)
    rec['hit'] = hit
    if hit:
        stats['hits'] += 1
        stats['mid_llen'][str(ev)] = stats['mid_llen'].get(str(ev), 0) + 1
    t1 = time.monotonic()
    served, wr = w.try_read(a.grace)
    rec['served_within_grace'] = served
    if served:
        rec['serve_ms'] = round((time.monotonic() - t1) * 1000, 3)
        rec['waiter_reply'] = show(wr)
        if hit:
            stats['served'] += 1
    else:
        if hit:
            stats['not_served'] += 1
        rec['llen_k_while_waiter_blocked'] = show(c.cmd('LLEN', k))
        rec['blocked_clients_while_stuck'] = blocked_clients(c)
        if a.long_every and stats['not_served'] % a.long_every == 1:
            served2, wr2 = w.try_read(a.long_wait)
            rec['long_wait_s'] = a.long_wait
            rec['served_after_long_wait'] = served2
            if served2:
                stats['served_after_long'] += 1
                rec['waiter_reply'] = show(wr2)
                served = True
            else:
                rec['llen_k_after_long_wait'] = show(c.cmd('LLEN', k))
                rec['blocked_after_long_wait'] = blocked_clients(c)
    if a.variant == 'hold':
        assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0) == 'OK'
        ok, mr = g.try_read(5)
        rec['mset_reply'] = show(mr) if ok else 'NO REPLY'
        if not served:
            served3, wr3 = w.try_read(2.0)
            rec['served_after_hold_release'] = served3
            if served3:
                stats['served_after_release'] += 1
                rec['waiter_reply'] = show(wr3)
                served = True
    if not served:
        # A plain push from another client: proves only the script push was missed.
        rec['plain_rpush_reply'] = show(c.cmd('RPUSH', k, 'wake'))
        served4, wr4 = w.try_read(2.0)
        rec['served_after_plain_push'] = served4
        if served4:
            stats['served_after_plain_push'] += 1
            rec['waiter_reply'] = show(wr4)
        else:
            stats['still_stuck'] += 1
            w.close(); w = s.conn()
            wait_blocked(c, 0)
    log.write(**rec)
    keys = [k, d] + ([pk, qk] if pk else [])
    c.cmd('DEL', *keys)
    if not wait_blocked(c, 0, timeout=2):
        log.write(event='warn', note='blocked_clients did not return to 0', i=i)

stats['geometry'] = geometry(a)
stats['variant'] = a.variant
stats['pusher'] = a.pusher
log.write(event='summary', **stats)
print('SUMMARY', stats)
print('log:', log.path)
log.close()
for x in (c, w, e, g):
    x.close()
s.stop()
