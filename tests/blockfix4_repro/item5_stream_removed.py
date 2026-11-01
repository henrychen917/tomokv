"""Item 5 BLOCK-STREAM-REMOVED-NO-UNBLOCK residual.

Per attempt: fresh stream s with group g (XGROUP CREATE s g $ MKSTREAM); waiter W sends
XREADGROUP GROUP g c1 BLOCK 0 STREAMS s > and is PARKED (INFO). Remover R then writes the case's
commands in ONE sendall. Active expiry is disabled (DEBUG SET-ACTIVE-EXPIRE 0) on both servers
so an expiry happens exactly at the first command of the batch that looks s up.
HIT = waiter parked + every command of the batch succeeded.
The waiter's exact reply within --grace is recorded; 'still blocked' = no reply.
"""
import sys
from pathlib import Path
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from common import base_args, boot, geometry, Log  # noqa: E402
import srv  # noqa: E402
from resp import Err, wait_blocked, blocked_clients, show  # noqa: E402


def recreate(s):
    return [['XGROUP', 'CREATE', s, 'g', '$', 'MKSTREAM'], ['XADD', s, '*', 'f', 'new']]


CASES = {
    'SET': lambda s: [['SET', s, 'x']],
    'SET+recreate': lambda s: [['SET', s, 'x'], ['DEL', s]] + recreate(s),
    'FLUSHDB': lambda s: [['FLUSHDB']],
    'FLUSHDB+recreate': lambda s: [['FLUSHDB']] + recreate(s),
    'FLUSHALL': lambda s: [['FLUSHALL']],
    'FLUSHALL+recreate': lambda s: [['FLUSHALL']] + recreate(s),
    'EXPIRE(EXISTS)': lambda s: [['EXISTS', s]],
    'EXPIRE(EXISTS)+recreate': lambda s: [['EXISTS', s]] + recreate(s),
    'EXPIRE-inside-recreate(ctl)': lambda s: recreate(s),
    'DEL+recreate(ctl)': lambda s: [['DEL', s]] + recreate(s),
    'DEL(ctl)': lambda s: [['DEL', s]],
    # RENAME recreation (the audit's residual): s2 holds group g and one undelivered entry
    'SET+RENAME': lambda s: [['SET', s, 'x'], ['RENAME', s + ':src', s]],
    'MSET+RENAME': lambda s: [['MSET', s, 'x', s + ':pad', 'y'], ['RENAME', s + ':src', s]],
    'EXPIRE(EXISTS)+RENAME': lambda s: [['EXISTS', s], ['RENAME', s + ':src', s]],
    'FLUSHDB+RENAME': lambda s: [['FLUSHDB'], ['XGROUP', 'CREATE', s + ':src', 'g', '$', 'MKSTREAM'],
                                 ['XADD', s + ':src', '*', 'f', 'renamed'], ['RENAME', s + ':src', s]],
    'FLUSHALL+RENAME': lambda s: [['FLUSHALL'], ['XGROUP', 'CREATE', s + ':src', 'g', '$', 'MKSTREAM'],
                                  ['XADD', s + ':src', '*', 'f', 'renamed'], ['RENAME', s + ':src', s]],
    'FLUSHDB-ASYNC+RENAME': lambda s: [['FLUSHDB', 'ASYNC'], ['XGROUP', 'CREATE', s + ':src', 'g', '$', 'MKSTREAM'],
                                       ['XADD', s + ':src', '*', 'f', 'renamed'], ['RENAME', s + ':src', s]],
    'FLUSHALL-ASYNC+RENAME': lambda s: [['FLUSHALL', 'ASYNC'], ['XGROUP', 'CREATE', s + ':src', 'g', '$', 'MKSTREAM'],
                                        ['XADD', s + ':src', '*', 'f', 'renamed'], ['RENAME', s + ':src', s]],
    'DEL+RENAME(ctl)': lambda s: [['DEL', s], ['RENAME', s + ':src', s]],
    'RENAME(ctl)': lambda s: [['RENAME', s + ':src', s]],
}
NEEDS_SRC = {'SET+RENAME', 'MSET+RENAME', 'EXPIRE(EXISTS)+RENAME', 'DEL+RENAME(ctl)', 'RENAME(ctl)'}

p = base_args('item 5 stream removed')
p.add_argument('--cases', default=','.join(CASES))
p.add_argument('--max-hits', type=int, default=200)
p.add_argument('--confirm', type=int, default=20, help='stop a case after N non-error outcomes')
p.add_argument('--grace', type=float, default=1.0)
p.add_argument('--long-wait', type=float, default=5.0)
a = p.parse_args()

s = boot(a, tag='item5-%s' % a.server)
log = Log('item5', a)
c, w, r = s.conn(), s.conn(), s.conn()
assert c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0) == 'OK'
wid = w.cmd('CLIENT', 'ID')
log.write(event='boot', geometry=geometry(a), version=s.version, bootline=s.bootline)
print('geometry:', geometry(a), '|', s.bootline)
run = '%x' % (int(time.time() * 1000) & 0xffffff)
summary = {}

for name in a.cases.split(','):
    build = CASES[name]
    st = dict(attempts=0, parked=0, hits=0, outcomes={}, long_released=0, long_checked=0)
    for i in range(a.max_hits * 2):
        st['attempts'] += 1
        sk = 'x5:%s:%s:%d' % (run, name.split('(')[0].replace('+', '_'), i)
        assert c.cmd('XGROUP', 'CREATE', sk, 'g', '$', 'MKSTREAM') == 'OK'
        if name in NEEDS_SRC:
            assert c.cmd('XGROUP', 'CREATE', sk + ':src', 'g', '$', 'MKSTREAM') == 'OK'
            c.cmd('XADD', sk + ':src', '*', 'f', 'renamed')
        expiry = name.startswith('EXPIRE')
        if expiry:
            assert c.cmd('PEXPIRE', sk, 60) == 1
            t_expire = time.monotonic() + 0.060
        w.send('XREADGROUP', 'GROUP', 'g', 'c1', 'BLOCK', 0, 'STREAMS', sk, '>')
        if not wait_blocked(c, 1):
            log.write(case=name, i=i, parked=False); w.close(); w = s.conn()
            wid = w.cmd('CLIENT', 'ID'); continue
        st['parked'] += 1
        if expiry:
            # never touch sk here: any lookup would expire it lazily before the batch
            delay = t_expire + 0.015 - time.monotonic()
            if delay > 0:
                time.sleep(delay)
        batch = build(sk)
        replies = r.pipeline(batch)
        ok = all(not isinstance(x, Err) for x in replies)
        if name.startswith('EXPIRE(EXISTS)'):
            ok = ok and replies[0] == 0          # the EXISTS observed the expiry
        hit = ok
        rec = dict(case=name, i=i, key=sk, batch=[' '.join(map(str, b[:1])) for b in batch],
                   replies=[show(x) for x in replies], hit=hit)
        if a.server == 'tomokv':
            rec['placement'] = srv.shards_of(c, sk, sk + ':src')
        served, wr = w.try_read(a.grace)
        if served:
            if isinstance(wr, Err):
                outcome = 'error: ' + str(wr).split(' ')[0]
            elif isinstance(wr, list):
                outcome = 'data'
            else:
                outcome = 'other: ' + show(wr)
            rec['waiter_reply'] = show(wr)
        else:
            outcome = 'still blocked after %.1fs' % a.grace
            rec['blocked_clients'] = blocked_clients(c)
            rec['type_s'] = show(c.cmd('TYPE', sk))
            if st['long_checked'] < 2:
                st['long_checked'] += 1
                ok2, wr2 = w.try_read(a.long_wait)
                rec['released_after_long_wait'] = show(wr2) if ok2 else 'no'
                if ok2:
                    st['long_released'] += 1
                    served = True
            if not served:
                rec['client_unblock'] = show(c.cmd('CLIENT', 'UNBLOCK', wid, 'ERROR'))
                ok3, wr3 = w.try_read(2)
                rec['after_unblock'] = show(wr3) if ok3 else 'no reply'
                if not ok3:
                    w.close(); w = s.conn(); wid = w.cmd('CLIENT', 'ID'); wait_blocked(c, 0)
        rec['outcome'] = outcome
        if hit:
            st['hits'] += 1
            st['outcomes'][outcome] = st['outcomes'].get(outcome, 0) + 1
        log.write(**rec)
        c.cmd('DEL', sk, sk + ':src')
        wait_blocked(c, 0, timeout=2)
        non_error = sum(v for k, v in st['outcomes'].items() if not k.startswith('error'))
        if st['hits'] >= a.max_hits or non_error >= a.confirm:
            break
    summary[name] = st
    first = None
    print('%-28s hits=%-4d outcomes=%s long_released=%d/%d' % (
        name, st['hits'], st['outcomes'], st['long_released'], st['long_checked']))
    log.write(event='case-summary', case=name, **st)

log.write(event='summary', geometry=geometry(a), results=summary)
print('log:', log.path)
log.close()
for y in (c, w, r):
    y.close()
s.stop()
