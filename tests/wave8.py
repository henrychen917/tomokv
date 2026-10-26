#!/usr/bin/env python3
"""Wave 8 EXEC claim, Lua helper and histogram integration, owned by execfair."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import sys
import threading
import uuid
from authfix import Resp
from _lib import encode
from latencyfix import histogram


def counters(c):
    return {k: int(v) for line in c.cmd('INFO', 'stats').decode().splitlines()
            if ':' in line for k, v in [line.split(':', 1)] if k.startswith('atomic_txn_')}


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
            pair = [names[0], next(k for k, r in zip(names, routes) if r[1] != first)]
            assert admin.cmd('MSET', pair[0], 0, pair[1], 0) == b'OK'
            assert admin.cmd('CONFIG', 'RESETSTAT') == b'OK'
            before = counters(admin)
            ready = threading.Barrier(12)
            rounds = 16
            script = """local a=redis.call('INCR',KEYS[1])
local b=redis.call('INCR',KEYS[2])
return cjson.encode({a,b,bit.band(7,3),struct.unpack('>I2',struct.pack('>I2',258)),
redis.sha1hex(cmsgpack.unpack(cmsgpack.pack('wave8')))})"""
            def worker(index):
                with Resp(port) as c:
                    ready.wait(timeout=10)
                    for _ in range(rounds):
                        if index < 8:
                            c.sock.sendall(encode('MULTI') + encode('INCR', pair[0]) +
                                encode('INCR', pair[1]) + encode('MGET', *pair) + encode('EXEC'))
                            assert c.read() == b'OK'
                            assert [c.read() for _ in range(3)] == [b'QUEUED'] * 3
                            result = c.read()
                            assert isinstance(result, list) and len(result) == 3, result
                            assert result[0] == result[1] and result[0] > 0, result
                            assert result[2] == [str(result[0]).encode()] * 2, result
                        else:
                            reply = c.cmd('EVAL', script, 2, *pair)
                            assert isinstance(reply, bytes), reply
                            result = json.loads(reply)
                            assert result[0] == result[1] and result[0] > 0, result
                            assert result[2:] == [3, 258, hashlib.sha1(b'wave8').hexdigest()], result
            with ThreadPoolExecutor(12) as pool:
                list(pool.map(worker, range(12)))
            calls = dict(histogram(admin, 'multi', 'exec', 'eval', 'incr', 'mget'))
            expected = {'multi': 8 * rounds, 'exec': 8 * rounds, 'eval': 4 * rounds,
                        'incr': 24 * rounds, 'mget': 8 * rounds}
            assert calls == expected, ('attempt', attempt, calls, expected)
            assert admin.cmd('MGET', *pair) == [str(12 * rounds).encode()] * 2
            after = counters(admin)
            delta = {k: v - before.get(k, 0) for k, v in after.items()}
            assert delta.get('atomic_txn_order_violations', 0) == 0, delta
            print(json.dumps(dict(attempt=attempt, histogram=calls, counters=delta)), flush=True)
            if delta.get('atomic_txn_fast_polls', 0) > 0:
                break
        else:
            raise AssertionError('EXEC fast-poll window never opened on three fresh states')
        assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'no') == b'OK'
        frozen = histogram(admin, 'get')
        for _ in range(8):
            assert admin.cmd('GET', pair[0]) == str(12 * rounds).encode()
        assert histogram(admin, 'get') == frozen
    print('PASS wave8 contended EXEC, helper scripts, exact child histogram counts and off transition')


if __name__ == '__main__':
    run(int(sys.argv[1]))
