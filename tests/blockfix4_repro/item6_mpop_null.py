"""Item 6 AT4.20-A0: LMPOP/ZMPOP answer null while a listed key still holds elements.

Keys: hot (first listed key) and fallback (second), placed on DIFFERENT owners (DEBUG SHARDS).
fallback is filled once and never refilled; the run's total pops are far below its size, so it
is non-empty for the whole run. ANY null MPOP reply is therefore a wrong reply.

--style atomfix5: 16 processes x 400 MPOPs; 8 of them push a unique item to hot before every
  MPOP (the atomfix5 reproduction). Hit proxy = MPOPs that ran while hot was contended:
  counted as MPOPs that took an element from hot plus nulls.
--style directed: per attempt, hot holds exactly one element; client A sends the MPOP and
  client B sends a plain pop of hot right after it (two sockets, back to back).
  HIT = B took hot's element (so A's MPOP raced it). DEFECT = A answered null.
"""
import multiprocessing as mp
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from common import base_args, boot, geometry, Log  # noqa: E402
import srv  # noqa: E402
from resp import Conn, Err, NIL_ARRAY, NIL_BULK, show  # noqa: E402

mp.set_start_method("fork", force=True)

p = base_args('item 6 MPOP null')
p.add_argument('--cmd', choices=['LMPOP', 'ZMPOP'], default='LMPOP')
p.add_argument('--style', choices=['atomfix5', 'directed'], default='atomfix5')
p.add_argument('--clients', type=int, default=16)
p.add_argument('--pushers', type=int, default=8)
p.add_argument('--ops', type=int, default=400)
p.add_argument('--rounds', type=int, default=3)
p.add_argument('--fallback', type=int, default=12000)
p.add_argument('--placement', choices=['cross-owner', 'same-owner'], default='cross-owner')
a = p.parse_args()


def mpop(conn, hot, fb):
    if a.cmd == 'LMPOP':
        return conn.cmd('LMPOP', 2, hot, fb, 'LEFT')
    return conn.cmd('ZMPOP', 2, hot, fb, 'MIN')


def classify(r, hot, fb):
    if r is NIL_ARRAY or r is NIL_BULK:
        return 'null'
    if isinstance(r, Err):
        return 'error'
    if isinstance(r, list) and len(r) == 2:
        key = r[0].decode()
        return 'hot' if key == hot else ('fallback' if key == fb else 'other')
    return 'other'


def worker(port, wid, hot, fb, pusher, ops, barrier, q):
    c = Conn(port, timeout=30)
    counts = dict(hot=0, fallback=0, null=0, error=0, other=0)
    samples = []
    barrier.wait()
    for j in range(ops):
        if pusher:
            if a.cmd == 'LMPOP':
                c.cmd('RPUSH', hot, 'w%d-%d' % (wid, j))
            else:
                c.cmd('ZADD', hot, j, 'w%d-%d' % (wid, j))
        r = mpop(c, hot, fb)
        k = classify(r, hot, fb)
        counts[k] += 1
        if k in ('null', 'error', 'other') and len(samples) < 5:
            samples.append(show(r))
    c.close()
    q.put((wid, counts, samples))


s = boot(a, tag='item6-%s' % a.server)
log = Log('item6', a, '%s-%s-%s' % (a.cmd, a.style, a.placement))
c = s.conn()
log.write(event='boot', geometry=geometry(a), version=s.version, bootline=s.bootline,
          cmd=a.cmd, style=a.style, placement=a.placement)
print('geometry:', geometry(a), '|', s.bootline, '|', a.cmd, a.style, a.placement)
run = '%x' % (int(time.time() * 1000) & 0xffffff)
total = dict(hot=0, fallback=0, null=0, error=0, other=0, rounds=0, contended=0, hits=0,
             defects=0, attempts=0)

for rnd in range(a.rounds):
    if a.server == 'tomokv':
        rel = 'owner_ne' if a.placement == 'cross-owner' else 'owner_eq'
        spec = [{'name': 'hot'}, {'name': 'fb', rel: 'hot'}]
        if a.placement == 'same-owner':
            spec[1]['shard_ne'] = 'hot'
        names, placed = srv.pick_keys(c, 'm6:%s:%d' % (run, rnd), spec)
        hot, fb = names['hot'], names['fb']
    else:
        hot, fb, placed = 'm6:%s:%d:hot' % (run, rnd), 'm6:%s:%d:fb' % (run, rnd), None
    # fill fallback in chunks
    n = a.fallback
    for base in range(0, n, 1000):
        chunk = range(base, min(n, base + 1000))
        if a.cmd == 'LMPOP':
            c.cmd('RPUSH', fb, *['f%d' % i for i in chunk])
        else:
            args = []
            for i in chunk:
                args += [i, 'f%d' % i]
            c.cmd('ZADD', fb, *args)
    fb_len0 = c.cmd('LLEN' if a.cmd == 'LMPOP' else 'ZCARD', fb)
    if a.style == 'atomfix5':
        barrier = mp.Barrier(a.clients)
        q = mp.Queue()
        procs = [mp.Process(target=worker, args=(a.port, wid, hot, fb, wid < a.pushers, a.ops,
                                                 barrier, q)) for wid in range(a.clients)]
        for pr in procs:
            pr.start()
        res = [q.get(timeout=600) for _ in procs]
        for pr in procs:
            pr.join()
        rc = dict(hot=0, fallback=0, null=0, error=0, other=0)
        samples = []
        for wid, counts, smp in res:
            for k2, v in counts.items():
                rc[k2] += v
            samples += smp
        fb_len1 = c.cmd('LLEN' if a.cmd == 'LMPOP' else 'ZCARD', fb)
        rec = dict(round=rnd, placement=placed, fallback_before=fb_len0, fallback_after=fb_len1,
                   **rc, samples=samples[:10])
        for k2, v in rc.items():
            total[k2] += v
        total['contended'] += rc['hot'] + rc['null']
        total['defects'] += rc['null']
        total['attempts'] += sum(rc.values())
        print('round', rnd, placed, rc, 'fallback', fb_len0, '->', fb_len1)
    else:
        ca, cb = s.conn(), s.conn()
        rc = dict(attempts=0, hits=0, defects=0, a_hot=0, a_fallback=0, a_null=0, b_nil=0)
        samples = []
        for j in range(a.ops):
            rc['attempts'] += 1
            if a.cmd == 'LMPOP':
                c.cmd('RPUSH', hot, 'h%d' % j)
                ca.send('LMPOP', 2, hot, fb, 'LEFT')
                cb.send('LPOP', hot)
            else:
                c.cmd('ZADD', hot, 0, 'h%d' % j)
                ca.send('ZMPOP', 2, hot, fb, 'MIN')
                cb.send('ZPOPMIN', hot)
            ra, rb = ca.read(), cb.read()
            ka = classify(ra, hot, fb)
            b_took = (rb not in (NIL_BULK, NIL_ARRAY)) and not (isinstance(rb, list) and not rb)
            if b_took:
                rc['hits'] += 1
            else:
                rc['b_nil'] += 1
            rc['a_' + ka] = rc.get('a_' + ka, 0) + 1
            if ka == 'null':
                rc['defects'] += 1
                if len(samples) < 5:
                    samples.append(dict(j=j, a=show(ra), b=show(rb)))
            c.cmd('DEL', hot)
        ca.close(); cb.close()
        fb_len1 = c.cmd('LLEN' if a.cmd == 'LMPOP' else 'ZCARD', fb)
        rec = dict(round=rnd, placement=placed, fallback_before=fb_len0, fallback_after=fb_len1,
                   **rc, samples=samples)
        total['attempts'] += rc['attempts']; total['hits'] += rc['hits']
        total['defects'] += rc['defects']
        print('round', rnd, placed, rc, 'fallback', fb_len0, '->', fb_len1)
    total['rounds'] += 1
    log.write(**rec)
    c.cmd('DEL', hot, fb)

total['geometry'] = geometry(a); total['cmd'] = a.cmd; total['style'] = a.style
total['placement'] = a.placement
log.write(event='summary', **total)
print('SUMMARY', total)
print('log:', log.path)
log.close()
c.close()
s.stop()
