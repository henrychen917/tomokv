#!/usr/bin/env python3
"""NT4.2: query-buffer and pre-AUTH limits with a multibulk frame pending.

Runs the same byte scripts against each listed server (e.g. PRE tomo, POST tomo,
Redis 7.4) and prints one JSON row per case: the exact reply bytes received and
whether the server closed the connection. The caller compares rows across
servers; --expect-equal A,B asserts byte-identical outcomes between two of them.
Every case uses a fresh connection. Server state is restored after each group.
"""
import argparse
import json
import socket
import time

from _lib import Conn, encode


def run(port, pieces, gap=.02, settle=1.0, auth=None):
    s = socket.create_connection(('127.0.0.1', port), timeout=5)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    received, closed = b'', False
    try:
        if auth:
            s.sendall(encode('AUTH', auth))
            assert s.recv(64) == b'+OK\r\n'
        for piece in pieces:
            try:
                s.sendall(piece)
            except (BrokenPipeError, ConnectionResetError):
                closed = True
                break
            time.sleep(gap)
        s.settimeout(settle)
        while True:
            try:
                data = s.recv(65536)
            except socket.timeout:
                break
            except ConnectionResetError:
                closed = True
                break
            if not data:
                closed = True
                break
            received += data
    finally:
        s.close()
    return received, closed


def small_args_frame(count, completed):
    """A frame announcing `count` 1-byte args whose first `completed` are sent."""
    return b'*%d\r\n' % count + b'$1\r\na\r\n' * completed


def cases():
    mib = 1 << 20
    # Query-buffer limit 1 MiB (authenticated client).
    yield 'qbuf', 'many completed args then over limit', [
        small_args_frame(400000, 100000), b'$1\r\na\r\n' * 60000, b'$1\r\na\r\n' * 10000]
    yield 'qbuf', 'decoded header, payload crosses limit', [
        b'*2\r\n$4\r\nECHO\r\n$2097152\r\n', b'x' * (mib // 2), b'x' * (mib // 2 + 1)]
    # 9 + 7 * 149795 + 2 bytes is exactly the 1 MiB limit (legal); the CRLF crosses it.
    yield 'qbuf', 'partial header crosses limit', [
        small_args_frame(200000, 149795), b'$1', b'\r\n']
    yield 'qbuf', 'frame exactly at limit then completes', [
        b'*2\r\n$4\r\nECHO\r\n$1048000\r\n', b'y' * 524288, b'y' * (1048000 - 524288) + b'\r\n']
    # Pre-AUTH limits (requirepass set, no AUTH): count, bulk, split across reads.
    yield 'preauth', 'count 11 split', [b'*1', b'1\r\n']
    yield 'preauth', 'count 10 then bulk 16385 split', [b'*10\r\n$5\r\nhello\r\n$163', b'85\r\n']
    yield 'preauth', 'MSET 4 pairs of 16384-byte bulks split mid payload', [
        b'*9\r\n$4\r\nMSET\r\n$16384\r\n' + b'z' * 8000, b'z' * 8384 + b'\r\n' +
        (b'$16384\r\n' + b'z' * 16384 + b'\r\n') * 7]
    yield 'preauth', 'pending AUTH frame completes', [b'*2\r\n$4\r\nAUTH\r\n$6\r\nsec', b'ret\r\n']
    yield 'preauth', 'inline 1 MiB without newline', [b'x' * 65536, b'x' * (mib - 65536)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('servers', nargs='+', help='label=port')
    ap.add_argument('--expect-equal', action='append', default=[])
    args = ap.parse_args()
    servers = [tuple(s.split('=', 1)) for s in args.servers]
    results = {}
    for label, port in servers:
        port = int(port)
        admin = Conn('127.0.0.1', port, timeout=10)
        original = admin.must('CONFIG', 'GET', 'client-query-buffer-limit')[1]
        for group, name, pieces in cases():
            if group == 'qbuf':
                admin.must('CONFIG', 'SET', 'client-query-buffer-limit', '1mb')
            else:
                admin.must('CONFIG', 'SET', 'requirepass', 'secret')
            try:
                reply, closed = run(port, pieces)
            finally:
                if group == 'qbuf':
                    admin.must('CONFIG', 'SET', 'client-query-buffer-limit', original)
                else:
                    admin.must('CONFIG', 'SET', 'requirepass', '')
            assert admin.must('PING') == b'PONG'
            results[(label, name)] = (reply, closed)
            print(json.dumps(dict(server=label, group=group, case=name, closed=closed,
                                  reply=reply.decode('latin1'))), flush=True)
        admin.close()
    for pair in args.expect_equal:
        a, b = pair.split(',')
        for (label, name), outcome in results.items():
            if label == a:
                assert outcome == results[(b, name)], (name, outcome, results[(b, name)])
        print(f'EQUAL {a} {b}: all cases byte-identical replies and identical close behavior')


if __name__ == '__main__':
    main()
