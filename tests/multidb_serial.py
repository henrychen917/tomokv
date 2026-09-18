#!/usr/bin/env python3
"""SWAPDB serial histories against a gate-owned server; --self-test opens no sockets.

Each writer owns one raw key and pipelines p32 SET/GET in DB 0 or 1. All writers
send before any reply is collected, so there are no real-time edges between
writers. Project onto each key and the one ordered SWAPDB history: legal
projections can be shuffled within each swap epoch into one global serial order.
Post-run probes in BOTH databases prevent a delayed stale stamp from being
accepted just because a pipelined GET happened to see the same stale namespace.
"""
import argparse
from functools import lru_cache
import json
import threading
import time
import uuid
from _lib import Conn, encode


def serial_epochs(ops, swaps):
    """Return one legal epoch per reply, or None. ops=(verb,db,value,start,end)."""
    @lru_cache(None)
    def visit(i, j, zero, one):
        if i == len(ops) and j == len(swaps):
            return ()
        if i < len(ops):
            verb, db, value, start, end = ops[i]
            # Any swap completed before invocation must already have happened.
            if j == len(swaps) or swaps[j][1] >= start:
                physical = db ^ (j & 1)
                values = [zero, one]
                if verb == 'SET':
                    values[physical] = value
                    match = True
                else:
                    match = values[physical] == value
                if match:
                    tail = visit(i + 1, j, *values)
                    if tail is not None:
                        return (j,) + tail
        if j < len(swaps):
            # Any operation replied before swap invocation must precede it.
            if i == len(ops) or ops[i][4] >= swaps[j][0]:
                return visit(i, j + 1, zero, one)
        return None
    return visit(0, 0, None, None)


def self_test():
    swap = [(2, 4)]
    assert serial_epochs([('SET', 0, b'v', 0, 1), ('GET', 1, b'v', 5, 6)], swap) == (0, 1)
    assert serial_epochs([('SET', 0, b'v', 5, 6), ('GET', 0, b'v', 7, 8)], swap) == (1, 1)
    # Supplied counterexample: late old stamp, missing read after swap, then value
    # appearing in logical 1. Neither placement of SET relative to SWAP can explain it.
    assert serial_epochs([('SET', 0, b'v', 0, 8), ('GET', 1, None, 3, 4),
                          ('GET', 1, b'v', 9, 10)], [(1, 2)]) is None
    assert serial_epochs([('SET', 0, b'v', 0, 1), ('GET', 0, b'v', 5, 6)], swap) is None
    print('PASS multidb serial oracle: both legal orders accepted; stale-stamp counterexample rejected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('host', nargs='?')
    parser.add_argument('port', nargs='?', type=int)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return
    assert args.host and args.port, 'gate-owned host and port required'
    admin = Conn(args.host, args.port, timeout=30)
    histories = []
    try:
        armed = 0
        for round_id in range(64):
            keys = [f'md-serial:{uuid.uuid4().hex}:{w}' for w in range(4)]
            ready = threading.Barrier(5, timeout=30)
            sent = threading.Barrier(4, timeout=30)
            rows = [None] * 4
            failures = []
            def writer(w):
                c = Conn(args.host, args.port, timeout=30)
                try:
                    assert c.cmd('SELECT', w % 2) == b'OK'
                    commands = []
                    values = []
                    for i in range(16):
                        value = f'{round_id}:{w}:{i}'.encode()
                        commands.extend([('SET', keys[w], value), ('GET', keys[w])])
                        values.extend([value, None])
                    wire = b''.join(encode(*command) for command in commands)
                    ready.wait()
                    start = time.monotonic_ns()
                    c.raw(wire)
                    sent.wait()  # no cross-writer real-time edge in the projections
                    history = []
                    for i, command in enumerate(commands):
                        reply = c.read()
                        end = time.monotonic_ns()
                        if command[0] == 'SET':
                            assert reply == b'OK', reply
                        history.append((command[0], w % 2, values[i] if command[0] == 'SET' else reply, start, end))
                    rows[w] = history
                except BaseException as error:
                    failures.append(repr(error))
                    ready.abort()
                    sent.abort()
                finally:
                    c.close()
            threads = [threading.Thread(target=writer, args=(w,), daemon=True) for w in range(4)]
            for thread in threads:
                thread.start()
            swaps = []
            try:
                ready.wait()
                for _ in range(16):
                    begin = time.monotonic_ns()
                    assert admin.cmd('SWAPDB', 0, 1) == b'OK'
                    swaps.append((begin, time.monotonic_ns()))
            finally:
                for thread in threads:
                    thread.join(30)
            assert not failures and not any(t.is_alive() for t in threads), failures
            assert max(row[0][3] for row in rows) < min(row[0][4] for row in rows), 'projection independence did not arm'
            overlap = any(start < row[-1][4] and end > row[0][3]
                          for start, end in swaps for row in rows)
            for db in (0, 1):
                assert admin.cmd('SELECT', db) == b'OK'
                for w, key in enumerate(keys):
                    begin = time.monotonic_ns()
                    reply = admin.cmd('GET', key)
                    rows[w].append(('GET', db, reply, begin, time.monotonic_ns()))
            for w, row in enumerate(rows):
                epochs = serial_epochs(row, swaps)
                assert epochs is not None, f'no serial SWAPDB order: round={round_id} writer={w} history={row!r} swaps={swaps!r}'
                histories.append(dict(round=round_id, writer=w, overlap=overlap,
                                      serial_reply_epochs=list(epochs), swaps=swaps,
                                      operations=[dict(verb=v, db=d, value=x.hex() if x is not None else None,
                                                       start=a, end=b) for v, d, x, a, b in row]))
            # Re-arm on fresh state, bounded. No unobserved overlap counts as a
            # concurrency witness; the C++ unit separately holds actual dispatch.
            armed += overlap
            if armed == 16:
                break
        assert armed == 16, f'only {armed}/16 overlapping windows armed in 64 attempts'
        if args.output:
            with open(args.output, 'w') as output:
                json.dump(histories, output, indent=2)
        print('PASS multidb serial history: 16 overlapping rounds, 4 writers, p32; serial epoch witness for every reply')
    finally:
        admin.close()


if __name__ == '__main__':
    main()
