#!/usr/bin/env python3
"""SV1 MAINLINE live proof. Attach only to a disposable 1s boot with >64 IO owners.

Default client balancing stays on. Owner geometry is witnessed, never assumed; fresh connections
are retried at most 16 times if balancing moves an owner before the disarm window is established.
"""
import argparse
import uuid
from _lib import Conn
from _gate_process import info, require


def owner(conn):
    return conn.must('DEBUG', 'IO-THREAD')


def pair(host, port):
    held = {}
    try:
        for _ in range(4096):
            conn = Conn(host, port, timeout=4)
            tid = owner(conn)
            mate = tid ^ 64
            if mate in held:
                other = held.pop(mate)
                for extra in held.values():
                    extra.close()
                return (conn, other) if tid < mate else (other, conn)
            if tid in held:
                conn.close()
            else:
                held[tid] = conn
        raise AssertionError('no owner pair i/i+64 in 4096 connections (no skip)')
    except BaseException:
        for conn in held.values():
            conn.close()
        raise


def witness(args, writer, kind):
    for roll in range(16):
        a, b = pair(args.host, args.port)
        try:
            owners = owner(a), owner(b)
            if owners[1] != owners[0] + 64:
                continue
            for conn in (a, b):
                conn.must('HELLO', 3)
                require(conn.must('CLIENT', 'TRACKING', 'ON') == b'OK', 'tracking armed')
            prefix = 'sv1:' + uuid.uuid4().hex
            key, other = prefix + ':a', prefix + ':b'
            require(a.must('GET', key) is None and b.must('GET', other) is None, 'fresh tracked misses')
            if (owner(a), owner(b)) != owners:
                continue
            before = int(info(writer, 'STATS')['tracking_invalidations'])
            writer.must('SET', key, 'first')
            require(a.read() == [b'invalidate', [key.encode()]], 'owner i initially receives invalidation')
            writer.must('SET', other, 'first')
            require(b.read() == [b'invalidate', [other.encode()]], 'owner i+64 initially receives invalidation')
            if kind == 'expiry':
                writer.must('SET', key, 'expires', 'PX', 2000)
            a.must('GET', key)
            require(b.must('CLIENT', 'TRACKING', 'OFF') == b'OK', 'owner i+64 disarmed')
            if (owner(a), owner(b)) != owners:
                continue
            # From here the exact hazard has fired. Missing delivery is a failure, not a retry.
            if kind == 'write':
                writer.must('SET', key, 'second')
            elif kind == 'flush':
                writer.must('FLUSHDB')
            expected = [b'invalidate', None if kind == 'flush' else [key.encode()]]
            require(a.read() == expected, f'{kind}: disarm retains delivery to owner i')
            require(int(info(writer, 'STATS')['tracking_invalidations']) >= before + 3,
                    'tracking invalidation counter witnessed both arms and post-disarm delivery')
            print(f'{kind}: PASS owners={owners}, fresh_roll={roll + 1}', flush=True)
            return
        finally:
            a.close()
            b.close()
    raise AssertionError(f'{kind}: no stable disarm window after 16 fresh rolls (no skip)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host')
    parser.add_argument('port', type=int)
    args = parser.parse_args()
    writer = Conn(args.host, args.port, timeout=5)
    try:
        row = info(writer, 'SERVER')
        require(row['thread_mode'] == '1s' and int(row['io_threads']) > 64,
                'requires witnessed 1s geometry with more than 64 IO owners')
        require(writer.must('CONFIG', 'GET', 'client-lb')[1] == b'1', 'default client balancing stays on')
        for kind in ('write', 'flush', 'expiry'):
            witness(args, writer, kind)
    finally:
        writer.close()


if __name__ == '__main__':
    main()
