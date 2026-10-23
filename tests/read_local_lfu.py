#!/usr/bin/env python3
"""RL4.1: every IO lane follows Redis's logarithmic LFU increment law.

Fresh keys start at five. With no eviction/expiry/decay, after N reads the
distribution is the Markov chain p(c -> c+1)=1/(10*(c-5)+1). The bounds come
from that distribution, not a fitted tolerance. PRE thread zero saturates.
"""
import math
import sys
import time
from _lib import Conn, encode, info

N, WIDTH = 300, 64


def moments():
    mass = {5: 1.0}
    for _ in range(N):
        following = {}
        for count, weight in mass.items():
            p = 1 / (10 * (count - 5) + 1)
            following[count] = following.get(count, 0) + weight * (1-p)
            following[count+1] = following.get(count+1, 0) + weight * p
        mass = following
    mean = sum(c*p for c, p in mass.items())
    variance = sum((c-mean)**2*p for c, p in mass.items())
    return mean, math.sqrt(variance / WIDTH)


def main():
    host, port = sys.argv[1], int(sys.argv[2])
    oracle = '--oracle' in sys.argv
    ctl = Conn(host, port)
    readers = {}
    try:
        ctl.must('CONFIG', 'SET', 'maxmemory', 1024*1024*1024)
        ctl.must('CONFIG', 'SET', 'maxmemory-policy', 'allkeys-lfu')
        if oracle:
            ctl.must('CONFIG', 'SET', 'lfu-decay-time', 0)
            tids = {0}
            readers[0] = Conn(host, port)
        else:
            server = info(ctl, 'server')
            assert server['read_local'] == '1', server
            tids = {int(k.removeprefix('read_local_thread_')) for k,v in server.items()
                    if k.startswith('read_local_thread_') and 'active=1' in v}
            count = server['fused_threads' if server['thread_mode'] == '1s' else 'io_threads']
            assert 0 in tids and len(tids) == int(count), server
            for _ in range(32 + 32*len(tids)):
                c = Conn(host, port)
                tid = c.must('DEBUG', 'IO-THREAD')
                if tid in tids and tid not in readers:
                    readers[tid] = c
                else:
                    c.close()
                if set(readers) == tids:
                    break
            assert set(readers) == tids, ('lanes never reached', tids-set(readers))
        mean, error = moments()
        failures = []
        for tid, reader in sorted(readers.items()):
            keys = [f'bugs5:lfu:{tid}:{i}' for i in range(WIDTH)]
            for key in keys:
                ctl.must('SET', key, 'v')
                assert ctl.must('OBJECT', 'FREQ', key) == 5
            # Warm lane admission without consuming LFU dice.
            reader.must('CLIENT', 'NO-TOUCH', 'ON')
            for _ in range(3):
                assert reader.must('MGET', *keys) == [b'v']*WIDTH
                time.sleep(.01)
            reader.must('CLIENT', 'NO-TOUCH', 'OFF')
            before = info(ctl, 'stats')
            for turn in range(N):
                if turn % 2:
                    assert reader.must('MGET', *keys) == [b'v']*WIDTH
                else:
                    reader.raw(b''.join(encode('GET', k) for k in keys))
                    assert [reader.read() for _ in keys] == [b'v']*WIDTH
            after = info(ctl, 'stats')
            if not oracle:
                gets = int(after['read_local_keyspace_hits'])-int(before['read_local_keyspace_hits'])
                mgets = int(after['read_local_mget_local_hits'])-int(before['read_local_mget_local_hits'])
                assert gets == N*WIDTH and mgets == N//2, ('not all reads lane-served', tid, gets, mgets)
                assert int(after['evicted_keys']) == int(before['evicted_keys']), 'eviction perturbed counts'
            counts = [ctl.must('OBJECT', 'FREQ', k) for k in keys]
            observed = sum(counts)/WIDTH
            print('thread', tid, 'counts', counts, 'mean', observed,
                  'Redis law', mean, '+/-', 6*error, flush=True)
            if abs(observed-mean) > 6*error:
                failures.append((tid, observed))
        assert not failures, failures
        print('lane LFU logarithmic probability PASS')
    finally:
        for c in readers.values():
            c.close()
        ctl.must('CONFIG', 'SET', 'maxmemory', 0)
        ctl.close()


if __name__ == '__main__':
    main()
