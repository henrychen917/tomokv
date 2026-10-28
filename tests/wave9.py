#!/usr/bin/env python3
"""Cross-lane contracts; run by the complete execfair gate job in all eight legs."""
import contextlib
import json
import select
import sys
import time
import uuid
from _lib import Conn, RespError, encode, stable_key_placement
from at412 import stats, wait, settle


def pair(c, prefix):
    keys = [prefix + str(i) for i in range(256)]
    _, routes = stable_key_placement(c, keys)
    return [keys[0], next(k for k, r in zip(keys, routes) if r[1] != routes[0][1])]


def blocked(c, n):
    wait(lambda: b'blocked_clients:' + str(n).encode() + b'\r\n' in
         c.must('INFO', 'clients'), 'blocking registration/retirement missing')


def exec_wakeup(c, port, keys):
    c.must('DEL', *keys)
    with contextlib.closing(Conn('127.0.0.1', port)) as waiter:
        waiter.send('BLPOP', keys[0], 0)
        blocked(c, 1)
        c.must('MULTI')
        assert c.must('RPUSH', keys[0], 'one') == b'QUEUED'
        assert c.must('RPUSH', keys[0], 'two') == b'QUEUED'
        assert c.must('SET', keys[1], 'cross') == b'QUEUED'
        assert c.must('EXEC') == [1, 2, b'OK']
        assert waiter.read() == [keys[0].encode(), b'one']
        assert c.must('LRANGE', keys[0], 0, -1) == [b'two']
        assert c.must('GET', keys[1]) == b'cross'
    blocked(c, 0)


def escalated_wakeup(c, port, keys):
    # A rival INCR invalidates the lead READ; force escalates that actual conflict.
    # Repeated RPUSH children must publish once after the escalated commit.
    c.must('DEL', *keys)
    c.must('SET', keys[0], 0)
    source = "local n=redis.call('INCR',KEYS[1]); redis.call('RPUSH',KEYS[2],'one'); " + \
             "redis.call('RPUSH',KEYS[2],'two'); return n"
    with contextlib.closing(Conn('127.0.0.1', port)) as waiter, \
         contextlib.closing(Conn('127.0.0.1', port)) as script:
        waiter.send('BLPOP', keys[1], 0)
        blocked(c, 1)
        before = stats(c)
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 300000)
        c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1)
        try:
            script.send('EVAL', source, 2, *keys)
            wait(lambda: stats(c)['script_stage_owner_tasks'] > before['script_stage_owner_tasks'],
                 'escalation lead READ never ran')
            assert c.must('INCR', keys[0]) == 1
            assert script.read() == 2
            assert waiter.read() == [keys[1].encode(), b'one']
            assert c.must('LRANGE', keys[1], 0, -1) == [b'two']
            after = stats(c)
            assert after['script_escalations'] == before['script_escalations'] + 1
            assert after['script_escalated_commits'] == before['script_escalated_commits'] + 1
        finally:
            c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
            c.must('DEBUG', 'SCRIPT-ESCALATE-FORCE', 0)
    blocked(c, 0)
    settle(c)


def fifo_pause(c, port, keys):
    c.must('MSET', keys[0], 0, keys[1], 0)
    clients = []
    try:
        owner = None
        for _ in range(256):
            x = Conn('127.0.0.1', port, timeout=6)
            current = x.must('DEBUG', 'IO-THREAD')
            if owner is None: owner = current
            if current == owner: clients.append(x)
            else: x.close()
            if len(clients) == 5: break
        assert len(clients) == 5, 'five connections on one IO required'
        before = stats(c)
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 1000000)
        read = "return {redis.call('GET',KEYS[1]),redis.call('GET',KEYS[2])}"
        write = "return {redis.call('INCR',KEYS[1]),redis.call('INCR',KEYS[2])}"
        for x in clients[:4]: x.send('EVAL_RO', read, 2, *keys)
        clients[4].send('EVAL', write, 2, *keys)
        wait(lambda: stats(c)['script_crossshard_window_waits'] >
             before['script_crossshard_window_waits'], 'fifth script never entered FIFO')
        c.must('CLIENT', 'PAUSE', 10000, 'WRITE')
        for x in clients[:4]: assert x.read() == [b'0', b'0']
        assert c.must('MGET', *keys) == [b'0', b'0'], 'paused FIFO head wrote'
        assert not select.select([clients[4].sock], [], [], .05)[0], 'paused script retired'
        c.must('CLIENT', 'UNPAUSE')
        assert clients[4].read() == [1, 1]
        assert c.must('MGET', *keys) == [b'1', b'1']
        assert stats(c)['script_crossshard_window_refusals'] == 0
    finally:
        c.must('CLIENT', 'UNPAUSE')
        c.must('DEBUG', 'SCRIPT-STAGE-DEFER', 0)
        for x in clients: x.close()
    settle(c)


def trimmed_stream_removal(c, port, key):
    # Trim real node accounting before removing a stream with a registered group
    # reader. Sequential DEL only: the parked wave-10 pipelined boundary is separate.
    key += '\r\nstream'
    group = 'wave9\r\ngroup'
    c.must('DEL', key)
    for i in range(1, 241): c.must('XADD', key, str(i)+'-0', 'f', 'v')
    removed = c.must('XTRIM', key, 'MAXLEN', '~', 20)
    assert removed > 0 and c.must('XLEN', key) == 240 - removed
    c.must('XGROUP', 'CREATE', key, group, '$')
    with contextlib.closing(Conn('127.0.0.1', port)) as reader:
        reader.send('XREADGROUP', 'GROUP', group, 'consumer', 'BLOCK', 0, 'STREAMS', key, '>')
        blocked(c, 1)
        assert c.must('DEL', key) == 1
        error = reader.read()
        assert isinstance(error, RespError) and str(error).startswith('NOGROUP'), error
        assert '\r' not in str(error) and '\n' not in str(error), error
        assert reader.must('PING') == b'PONG', 'sanitized removal reply broke framing'
    blocked(c, 0)


def run(port):
    with contextlib.closing(Conn('127.0.0.1', port, timeout=8)) as c:
        keys = pair(c, 'wave9:' + uuid.uuid4().hex + ':')
        exec_wakeup(c, port, keys)
        escalated_wakeup(c, port, keys)
        fifo_pause(c, port, keys)
        trimmed_stream_removal(c, port, keys[0])
        print(json.dumps(dict(wave9='PASS', contracts=['EXEC repeated-key wakeup',
            'escalated script commit wakeup', 'FIFO PAUSE WRITE',
            'trim accounting/removal/sanitized NOGROUP'])), flush=True)

if __name__ == '__main__': run(int(sys.argv[1]))
