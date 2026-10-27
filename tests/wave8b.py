#!/usr/bin/env python3
"""CONFIG transitions while EXEC/script fragments are demonstrably pending."""
from concurrent.futures import ThreadPoolExecutor
import sys
import uuid
from authfix import Resp
from _lib import encode
from latencyfix import histogram
from wave8 import await_counter, counters, queue_exec

SCRIPT = "return {redis.call('INCRBY',KEYS[1],1),redis.call('INCRBY',KEYS[2],1)}"


def run(port):
    with Resp(port) as admin:
        for case in ('exec', 'script'):
            for attempt in range(3):
                names = ['wave8b:' + uuid.uuid4().hex + ':' + str(i) for i in range(256)]
                routes = admin.cmd('DEBUG', 'SHARDS', *names)
                keys = [names[0], next(k for k, r in zip(names, routes) if r[1] != routes[0][1])]
                assert admin.cmd('MSET', keys[0], 0, keys[1], 0) == b'OK'
                assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'yes') == b'OK'
                before = counters(admin)
                debug = 'TXN-PLACE-DEFER' if case == 'exec' else 'SCRIPT-STAGE-DEFER'
                witness = 'atomic_txn_fast_polls' if case == 'exec' else 'script_stage_owner_tasks'
                with Resp(port) as client, ThreadPoolExecutor(1) as pool:
                    assert admin.cmd('DEBUG', debug, 400000) == b'OK'
                    try:
                        if case == 'exec':
                            queue_exec(client, keys)
                        else:
                            client.sock.sendall(encode('EVAL', SCRIPT, 2, *keys))
                        pending = pool.submit(client.read)
                        await_counter(admin, before, witness)
                        assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'no') == b'OK'
                        off_pending = not pending.done()
                        assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'yes') == b'OK'
                        on_pending = not pending.done()
                        result = pending.result(timeout=10)
                        expected = [1, 1, [b'1', b'1']] if case == 'exec' else [1, 1]
                        assert result == expected, (case, result)
                    finally:
                        assert admin.cmd('DEBUG', debug, 0) == b'OK'
                if off_pending and on_pending:
                    break
            else:
                raise AssertionError((case, 'no pending CONFIG transition on three fresh states'))

            # Completed off traffic cannot publish anything, even with old stores.
            assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'no') == b'OK'
            assert admin.cmd('CONFIG', 'RESETSTAT') == b'OK'
            with Resp(port) as client:
                queue_exec(client, keys)
                assert client.read() == [2, 2, [b'2', b'2']]
                assert client.cmd('EVAL', SCRIPT, 2, *keys) == [3, 3]
            assert dict(histogram(admin, 'exec', 'incr', 'eval', 'incrby', 'mget')) == {}
            assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'yes') == b'OK'
            with Resp(port) as client:
                queue_exec(client, keys)
                assert client.read() == [4, 4, [b'4', b'4']]
                assert client.cmd('EVAL', SCRIPT, 2, *keys) == [5, 5]
            actual = dict(histogram(admin, 'exec', 'incr', 'eval', 'incrby', 'mget'))
            assert actual == dict(exec=1, incr=2, eval=1, incrby=2, mget=1), actual
            print('PASS wave8b pending', case, 'CONFIG no/yes; exact off/on samples', actual, flush=True)
        assert admin.cmd('CONFIG', 'SET', 'latency-tracking', 'no') == b'OK'


if __name__ == '__main__':
    run(int(sys.argv[1]))
