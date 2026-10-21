#!/usr/bin/env python3
"""NT4.2 live witness: partial multibulk frames pending across FLIP client transfers.

Connects to a caller-owned 2s server booted with --client-lb 0 --key-lb 0
--flip-auto 0 --enable-debug-command yes. Every client parks a different partial
shape (count line, bulk header, decoded header without payload, mid-payload,
and three >1 Mi-argument frames), the IO pool is FLIPped (EX->IO, then back), and
each frame is completed on whichever IO thread now owns it. Required: FLIP
reports transfers, at least one parked client changed owner in each direction,
every reply is exact, and every value reads back byte-identical.
"""
import argparse
from contextlib import closing
import time

from _lib import Conn, RespError, encode


def shapes(index, key, value):
    frame = encode('SET', key, value)
    header_end = frame.index(b'$%d\r\n' % len(value)) + len(b'$%d\r\n' % len(value))
    cuts = [2, header_end - 3, header_end, header_end + 1 + index * 97 % (len(value) - 2)]
    cut = cuts[index % len(cuts)]
    return frame[:cut], frame[cut:]


def flip_report(control):
    reply = control.must('FLIP')
    return {k.decode() if isinstance(k, bytes) else k: v for k, v in zip(reply[::2], reply[1::2])}


def owners(conns):
    return [c.must('DEBUG', 'IO-THREAD') for c in conns]


def client_rows(control):
    rows = {}
    for line in control.must('CLIENT', 'LIST').splitlines():
        fields = dict(item.split(b'=', 1) for item in line.split())
        rows[int(fields[b'id'])] = fields
    return rows


def round_trip(control, host, port, target_io, target_ex, tag, count, bigs=3):
    # Frames above the 1 Mi fast-path bound use the exceptional-count decoder; open these
    # connections first so they are among the oldest on every io thread.
    big = [Conn(host, port, timeout=60) for _ in range(bigs)]
    conns = [Conn(host, port, timeout=30) for _ in range(count)]
    try:
        before = owners(conns)
        ids = [int(c.must('CLIENT', 'ID')) for c in conns]
        values = [(b'%s:%d:' % (tag.encode(), i)) * (2000 + i) for i in range(count)]
        tails = []
        for i, c in enumerate(conns):
            head, tail = shapes(i, f'rr:{tag}:{i}', values[i])
            c.raw(head)
            tails.append(tail)
        # Frames above the 1 Mi fast-path bound, parked after their first megabyte.
        big_before = owners(big)
        big_ids = [int(b.must('CLIENT', 'ID')) for b in big]
        n = (1 << 20) + 7
        frame = b'*%d\r\n$4\r\nPING\r\n' % n + b'$1\r\na\r\n' * (n - 1)
        for b in big:
            b.raw(frame[:1 << 20])
        deadline = time.monotonic() + 10
        while True:
            rows = client_rows(control)
            pending = [int(rows.get(i, {}).get(b'qbuf', b'0')) for i in ids + big_ids]
            if all(p > 0 for p in pending):
                break
            assert time.monotonic() < deadline, ('partial frames never buffered', pending)
            time.sleep(.01)
        assert control.must('FLIP', target_io, target_ex) == b'OK'
        report = flip_report(control)
        assert int(report['live_io']) == target_io and int(report['live_ex']) == target_ex, report
        transfers = int(report['last_transfers'])
        assert transfers > 0, ('FLIP moved nobody', report)
        for c, tail in zip(conns, tails):
            c.raw(tail)
        for i, c in enumerate(conns):
            assert c.read() == b'OK', i
        for b in big:
            b.raw(frame[1 << 20:])
        for b in big:
            assert b.read() == RespError(b"ERR wrong number of arguments for 'ping' command")
        after = owners(conns)
        big_after = owners(big)
        moved = sum(a != b for a, b in zip(before, after))
        big_moved = sum(a != b for a, b in zip(big_before, big_after))
        assert moved + big_moved > 0, 'no parked frame crossed an ownership edge'
        for i, c in enumerate(conns):
            assert c.must('GET', f'rr:{tag}:{i}') == values[i], i
            assert c.must('PING') == b'PONG'
        return dict(tag=tag, target=[target_io, target_ex], transfers=transfers,
                    parked=count + len(big), moved_while_parked=moved + big_moved,
                    over_1mi_moved=big_moved)
    finally:
        for c in conns + big:
            c.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('host')
    ap.add_argument('port', type=int)
    ap.add_argument('--clients', type=int, default=48)
    args = ap.parse_args()
    with closing(Conn(args.host, args.port, timeout=30)) as control:
        assert control.must('CONFIG', 'GET', 'client-lb') == [b'client-lb', b'0']
        initial = flip_report(control)
        io, ex = int(initial['live_io']), int(initial['live_ex'])
        assert ex >= 2, initial
        results = [round_trip(control, args.host, args.port, io + 1, ex - 1, 'grow', args.clients),
                   round_trip(control, args.host, args.port, io, ex, 'shrink', args.clients)]
    for r in results:
        print(r, flush=True)
    print('PASS respresume FLIP: parked partial frames completed after owner transfer')


if __name__ == '__main__':
    main()
