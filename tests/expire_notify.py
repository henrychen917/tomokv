#!/usr/bin/env python3
"""C2: notifications follow the visible version and actual expiration.

RENAME preserves a TTL on a foreign candidate; plain MSET clears it. Both are
held across distinct owners. Three fresh arms at most must witness the live
predecessor, an undecided group and its installed entries before the deadline.
"""
import argparse
import select
import time

from compat2_support import Client, arguments, save, server, stats, wait_for
from _lib import topology


def keys(c):
    owners = topology(c).shard_owner
    found = {}
    for i in range(4096):
        key = f'compat2:notify:{i}'
        sid = c.cmd('DEBUG', 'SHARD', key)
        found.setdefault(owners[sid], (key, sid))
        if len(found) == 2:
            return list(found.values())
    raise AssertionError('two distinct owners were not found')


def events(sub):
    sub.send('PING', 'compat2-barrier')
    result = []
    while (row := sub.read()) != [b'pong', b'compat2-barrier']:
        assert row[0] == b'message', row
        result.append(row)
    return result


def run(a):
    a.output.mkdir(parents=True, exist_ok=False)
    receipt = []
    with server(a.binary, a.output / 'server', a.port, a.cores, a.mode, a.engine,
                extra=['--atomic', '1']), Client(a.port) as c, Client(a.port) as group, \
                Client(a.port) as sub:
        c.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'Exm')
        c.cmd('DEBUG', 'SET-ACTIVE-EXPIRE', 0)
        sub.send('SUBSCRIBE', '__keyevent@0__:expired', '__keyevent@0__:keymiss')
        sub.read(); sub.read()
        (ka, sa), (kb, sb) = keys(c)
        receipt.append(dict(geometry=[ka, sa, kb, sb], mode=a.mode, engine=a.engine))
        for kind in ('MSET', 'RENAME'):
            for attempt in range(3):
                assert c.cmd('FLUSHDB') == b'OK'
                assert c.cmd('SET', ka, 'old') == b'OK'
                assert c.cmd('SET', kb, 'candidate') == b'OK'
                deadline = time.time_ns() // 1000000 + 700
                assert c.cmd('PEXPIREAT', kb, deadline) == 1
                before = stats(c)
                events(sub)
                assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 1) == b'OK'
                armed = False
                try:
                    group.send(*(['RENAME', kb, ka] if kind == 'RENAME' else
                                 ['MSET', ka, 'new', kb, 'new']))
                    installed = wait_for(lambda: (s if (s := stats(c))[
                        'atomic_pending_entries'] >= 2 else None), 'group not installed')
                    assert not select.select([group.s], [], [], 0)[0], 'group already replied'
                    old = c.cmd('GET', ka)
                    armed = time.time_ns() // 1000000 < deadline
                    if armed:
                        assert old == b'old' and c.cmd('PTTL', ka) == -1
                        while time.time_ns() // 1000000 <= deadline + 20:
                            time.sleep(.002)
                        replies = [c.cmd('GET', ka) for _ in range(3)]
                        after = stats(c)
                        wait_for(lambda: stats(c)['pubsub_inflight'] == 0,
                                 'notifications did not drain')
                        early = events(sub)
                        assert not select.select([group.s], [], [], 0)[0], 'hold escaped'
                        receipt.append(dict(kind=kind, attempt=attempt, deadline=deadline,
                            pending=installed['atomic_pending_entries'], before=before,
                            after=after, replies=replies, early=early))
                finally:
                    assert c.cmd('DEBUG', 'ATOMIC-COMMIT-HOLD', 0) == b'OK'
                assert group.read() == b'OK'
                if armed:
                    break
            else:
                raise AssertionError('three fresh states missed the candidate deadline')
            save(a.output / 'results.json', receipt)
            assert replies == [b'old'] * 3, 'foreign candidate became visible'
            assert after['expired_keys'] == before['expired_keys'], 'read erased retained state'
            assert early == [], 'expired notification for an invisible candidate'
            assert after['notify_events_fired'] == before['notify_events_fired'], \
                'notification was emitted even if delivery has not completed'
            wait_for(lambda: stats(c)['atomic_pending_entries'] == 0, 'group not retired')
            if kind == 'MSET':
                assert c.cmd('MGET', ka, kb) == [b'new', b'new']
                assert c.cmd('PTTL', ka) == -1 and c.cmd('PTTL', kb) == -1

        # A separate ordinary expired key proves the x notification was really armed.
        assert c.cmd('SET', ka, 'live', 'PX', 100) == b'OK'
        deadline = c.cmd('PEXPIRETIME', ka)
        assert c.cmd('GET', ka) == b'live', 'positive expiry control missed its live arm'
        while time.time_ns() // 1000000 <= deadline + 20:
            time.sleep(.002)
        before = stats(c)
        events(sub)
        assert c.cmd('GET', ka) is None
        required = [sub.read(), sub.read()]
        assert required == [[b'message', b'__keyevent@0__:expired', ka.encode()],
                            [b'message', b'__keyevent@0__:keymiss', ka.encode()]], required
        assert stats(c)['expired_keys'] == before['expired_keys'] + 1
        receipt.append(dict(positive_control=required))
        save(a.output / 'results.json', receipt)
    print('expire_notify: held MSET and expiring RENAME, plus real expiry control PASS')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    arguments(p)
    run(p.parse_args())
