#!/usr/bin/env python3
"""Directed wave6 interactions in the existing EXEC gate's eight declared legs."""
import concurrent.futures
import sys
import time
import uuid
from clientfix import Conn, Error

port = int(sys.argv[1])
prefix = 'wave6:' + uuid.uuid4().hex + ':'


def equal(actual, expected):
    assert actual == expected, (actual, expected)


def transaction(client, commands):
    replies = client.pipe([('MULTI',), *commands, ('EXEC',)])
    equal(replies[:-1], [b'OK'] + [b'QUEUED'] * len(commands))
    assert isinstance(replies[-1], list), replies[-1]
    return replies[-1]


with Conn(port) as admin:
    names = [prefix + str(i) for i in range(256)]
    routes = admin.cmd('DEBUG', 'SHARDS', *names)
    left = names[0]
    right = next(key for key, route in zip(names, routes) if route[1] != routes[0][1])
    equal(admin.cmd('CONFIG', 'SET', 'list-max-listpack-size', 4), b'OK')
    equal(admin.cmd('RPUSH', left, *['v'] * 8), 8)
    equal(admin.cmd('SADD', right, *range(32)), 32)
    reply = transaction(admin, [('LTRIM', left, 0, 1), ('SPOP', right, 28),
        ('OBJECT', 'ENCODING', left), ('OBJECT', 'ENCODING', right),
        ('LRANGE', left, 0, -1), ('SCARD', right)])
    equal(reply[0], b'OK')
    assert len(reply[1]) == len(set(reply[1])) == 28, reply
    equal(reply[2:], [b'listpack', b'intset', [b'v', b'v'], 4])
    print('PASS EXEC cross-owner list/set encoding transitions', flush=True)

    missing = prefix + 'missing'
    reply = transaction(admin, [('XINFO', 'STREAM', missing, 'FULL', 'COUNT', 1, 'extra')])
    equal(reply, [Error('ERR no such key')])
    user = prefix + 'user'
    equal(admin.cmd('ACL', 'SETUSER', user, 'on', 'nopass', '~' + prefix + '*',
                    '-@all', '+multi', '+exec', '+object|encoding'), b'OK')
    with Conn(port) as limited:
        equal(limited.cmd('AUTH', user, ''), b'OK')
        equal(transaction(limited, [('OBJECT', 'ENCODING', left)]), [b'listpack'])
        equal(limited.cmd('MULTI'), b'OK')
        denied = limited.cmd('OBJECT', 'REFCOUNT', left)
        assert isinstance(denied, Error) and denied.startswith('NOPERM'), denied
        abort = limited.cmd('EXEC')
        assert isinstance(abort, Error) and abort.startswith('EXECABORT'), abort
    equal(admin.cmd('ACL', 'DELUSER', user), 1)
    print('PASS EXEC container precedence and child ACL grants', flush=True)

    raw = prefix + 'raw'
    equal(admin.cmd('SET', raw, b'\0' * 4096), b'OK')
    with Conn(port) as sub:
        equal(sub.cmd('PSUBSCRIBE', '__key*__:*'), [b'psubscribe', b'__key*__:*', 1])
        equal(admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', 'KEA'), b'OK')
        equal(transaction(admin, [('SETBIT', raw, 0, 0), ('SETBIT', raw, 0, 1)]), [0, 0])
        expected = [[b'pmessage', b'__key*__:*', b'__keyspace@0__:' + raw.encode(), b'setbit'],
                    [b'pmessage', b'__key*__:*', b'__keyevent@0__:setbit', raw.encode()]]
        equal([sub.read(), sub.read()], expected)
        equal(sub.cmd('PING', 'wave6-barrier'), [b'pong', b'wave6-barrier'])
        equal(sub.drain(.04), [])
    equal(admin.cmd('CONFIG', 'SET', 'notify-keyspace-events', ''), b'OK')
    print('PASS EXEC no-op SETBIT silence and ordered changed-bit events', flush=True)

    blocked_key = prefix + 'blocked'
    with Conn(port) as waiter, concurrent.futures.ThreadPoolExecutor(1) as pool:
        waiter.s.settimeout(5)
        pending = pool.submit(waiter.cmd, 'BLPOP', blocked_key, 3)
        deadline = time.monotonic() + 2
        while b'blocked_clients:1\r\n' not in admin.cmd('INFO', 'clients'):
            assert time.monotonic() < deadline, 'BLPOP never armed'
            time.sleep(.005)
        equal(transaction(admin, [('RPUSH', blocked_key, 'served')]), [1])
        equal(pending.result(timeout=4), [blocked_key.encode(), b'served'])
        equal(admin.cmd('LLEN', blocked_key), 0)
    print('PASS EXEC publication wakes an armed blocking serve exactly once', flush=True)
