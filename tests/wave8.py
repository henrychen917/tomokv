#!/usr/bin/env python3
"""Wave 8 EXEC claim, Lua helper and histogram integration, owned by execfair."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
import threading
import time
import uuid
from authfix import Resp
from _lib import encode
from latencyfix import histogram


def counters(c):
    return {k: int(v) for line in c.cmd('INFO', 'stats').decode().splitlines()
            if ':' in line for k, v in [line.split(':', 1)]
            if k.startswith(('atomic_txn_', 'script_'))}



def await_counter(admin, before, key):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        current = counters(admin)
        if current[key] > before[key]:
            return current
        time.sleep(.001)
    raise AssertionError(('arming witness missing', key, before, current))


def queue_exec(c, keys):
    c.sock.sendall(encode('MULTI') + encode('INCR', keys[0]) +
                  encode('INCR', keys[1]) + encode('MGET', *keys) + encode('EXEC'))
    assert c.read() == b'OK'
    assert [c.read() for _ in range(3)] == [b'QUEUED'] * 3


def retry_windows(admin, port, pair, script):
    # Existing debug boundaries open precise windows; no success depends on a
    # naturally rare retry. Every failed arming is rerolled on fresh keys.
    for case in ('exec', 'script'):
        for attempt in range(3):
            names = ['wave8-retry:' + uuid.uuid4().hex + ':' + str(i) for i in range(256)]
            routes = admin.cmd('DEBUG', 'SHARDS', *names)
            keys = [names[0], next(k for k,r in zip(names,routes) if r[1] != routes[0][1])]
            assert admin.cmd('MSET', keys[0], 0, keys[1], 0) == b'OK'
            assert admin.cmd('CONFIG', 'RESETSTAT') == b'OK'
            before = counters(admin)
            with Resp(port) as older, Resp(port) as younger:
                if case == 'exec':
                    assert admin.cmd('DEBUG', 'TXN-PLACE-DEFER', 400000) == b'OK'
                    queue_exec(older, keys)
                    await_counter(admin, before, 'atomic_txn_fast_polls')
                    queue_exec(younger, keys[::-1])
                    replies = [older.read(), younger.read()]
                    assert sorted(r[0] for r in replies) == [1, 2], replies
                    assert all(r[0] == r[1] and r[2] == [str(r[0]).encode()] * 2 for r in replies), replies
                    actual = dict(histogram(admin, 'exec', 'incr', 'mget'))
                    assert actual == dict(exec=2, incr=4, mget=2), actual
                    witness = 'atomic_txn_retries'
                else:
                    assert admin.cmd('DEBUG', 'SCRIPT-STAGE-DEFER', 400000) == b'OK'
                    try:
                        older.sock.sendall(encode('EVAL', script, 2, *keys))
                        await_counter(admin, before, 'script_stage_owner_tasks')
                        assert younger.cmd('SET', keys[0], 10) == b'OK'
                        assert younger.cmd('SET', keys[1], 10) == b'OK'
                        result = json.loads(older.read())
                        assert result[:2] == [11, 11], result
                        assert result[2:] == [3, 258, hashlib.sha1(b'wave8').hexdigest()], result
                    finally:
                        assert admin.cmd('DEBUG', 'SCRIPT-STAGE-DEFER', 0) == b'OK'
                    actual = dict(histogram(admin, 'eval', 'incrby'))
                    assert actual == dict(eval=1, incrby=2), actual
                    witness = 'script_group_occ_retries'
            delta = counters(admin)[witness] - before[witness]
            print(json.dumps(dict(window=case, attempt=attempt, retries=delta, histogram=actual)), flush=True)
            if delta > 0:
                break
        else:
            raise AssertionError((case, 'retry window never opened on three fresh states'))

def run(port):
    with Resp(port) as admin:
        assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'yes') == b'OK'
        # Fresh connections and keys each round; never accept a missing fast-poll
        # witness. No rates are measured and no timing tolerance is widened.
        for attempt in range(3):
            prefix = 'wave8:' + uuid.uuid4().hex + ':'
            names = [prefix + str(i) for i in range(256)]
            routes = admin.cmd('DEBUG', 'SHARDS', *names)
            first = routes[0][1]
            left = [k for k, r in zip(names, routes) if r[1] == first]
            right = [k for k, r in zip(names, routes) if r[1] != first]
            assert len(left) >= 5 and len(right) >= 5
            pair = [left[0], right[0]]
            script_pairs = list(zip(left[1:3], right[1:3]))
            script_pairs[1] = tuple(reversed(script_pairs[1]))
            # Distinct script claims isolate successful-command accounting while
            # six EXEC clients contend. AT4.12 admission queues even under load;
            # no BUSY or TRYAGAIN refusal is permitted in any reply.
            for keys in [pair, *script_pairs]:
                assert admin.cmd('MSET', keys[0], 0, keys[1], 0) == b'OK'
            assert admin.cmd('CONFIG', 'RESETSTAT') == b'OK'
            before = counters(admin)
            ready = threading.Barrier(8)
            rounds = 16
            script = """local a=redis.call('INCRBY',KEYS[1],1)
local b=redis.call('INCRBY',KEYS[2],1)
return cjson.encode({a,b,bit.band(7,3),struct.unpack('>I2',struct.pack('>I2',258)),
redis.sha1hex(cmsgpack.unpack(cmsgpack.pack('wave8')))})"""
            def worker(index):
                with Resp(port) as c:
                    ready.wait(timeout=10)
                    for _ in range(rounds):
                        if index < 6:
                            order = pair if index % 2 == 0 else pair[::-1]
                            c.sock.sendall(encode('MULTI') + encode('INCR', order[0]) +
                                encode('INCR', order[1]) + encode('MGET', *pair) + encode('EXEC'))
                            assert c.read() == b'OK'
                            assert [c.read() for _ in range(3)] == [b'QUEUED'] * 3
                            result = c.read()
                            assert isinstance(result, list) and len(result) == 3, result
                            assert result[0] == result[1] and result[0] > 0, result
                            assert result[2] == [str(result[0]).encode()] * 2, result
                        else:
                            reply = c.cmd('EVAL', script, 2, *script_pairs[index - 6])
                            assert isinstance(reply, bytes), reply
                            result = json.loads(reply)
                            assert result[0] == result[1] and result[0] > 0, result
                            assert result[2:] == [3, 258, hashlib.sha1(b'wave8').hexdigest()], result
            with ThreadPoolExecutor(8) as pool:
                list(pool.map(worker, range(8)))
            calls = dict(histogram(admin, 'multi', 'exec', 'eval', 'incr', 'incrby', 'mget'))
            expected = {'multi': 6 * rounds, 'exec': 6 * rounds, 'eval': 2 * rounds,
                        'incr': 12 * rounds, 'incrby': 4 * rounds, 'mget': 6 * rounds}
            assert calls == expected, ('attempt', attempt, calls, expected)
            assert admin.cmd('MGET', *pair) == [str(6 * rounds).encode()] * 2
            for keys in script_pairs:
                assert admin.cmd('MGET', *keys) == [str(rounds).encode()] * 2
            after = counters(admin)
            delta = {k: v - before.get(k, 0) for k, v in after.items()}
            assert delta.get('atomic_txn_order_violations', 0) == 0, delta
            print(json.dumps(dict(attempt=attempt, histogram=calls, counters=delta)), flush=True)
            if delta.get('atomic_txn_fast_polls', 0) > 0:
                break
        else:
            raise AssertionError('EXEC fast-poll window never opened on three fresh states')
        retry_windows(admin, port, pair, script)
        assert counters(admin)['script_crossshard_window_refusals'] == 0
        assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'no') == b'OK'
        value = admin.cmd('GET', pair[0])
        frozen = histogram(admin, 'get')
        for _ in range(8):
            assert admin.cmd('GET', pair[0]) == value
        assert histogram(admin, 'get') == frozen
    print('PASS wave8 contended EXEC, helper scripts, exact child histogram counts and off transition')


if __name__ == '__main__':
    run(int(sys.argv[1]))
