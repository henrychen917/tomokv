#!/usr/bin/env python3
"""Cross-owner atomic-0 movers: exact deliveries, resumed waiters and live pops.

Run on the same debug geometry as txngroup. No timing-based pass: blocking
variants must register all four waiters before the producer seeds their list.
"""
import argparse
import concurrent.futures
import threading

import _lib
from txniso import Battery


def move(b, name, left="RIGHT", to="LEFT", count=2000):
    src, dst = b.pair()
    expected = {f"{i}".encode() for i in range(count)}
    blocking = name in ("BLMOVE", "BRPOPLPUSH")
    if not blocking:
        b.admin.must("RPUSH", src, *sorted(expected))
    if name in ("LMOVE", "BLMOVE"):
        command = [name, src, dst, left, to] + ([0] if blocking else [])
    else:
        command = [name, src, dst] + ([0] if blocking else [])
    clients = [b.conn(timeout=30) for _ in range(4)]
    start = threading.Barrier(5)

    def worker(c):
        start.wait()
        return [c.must(*command) for _ in range(count // 4)]

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(worker, c) for c in clients]
        start.wait()
        if blocking:
            b.wait(lambda: int(_lib.info(b.admin, "clients")["blocked_clients"]) == 4,
                   "four blocking movers never registered", timeout=5)
            b.admin.must("RPUSH", src, *sorted(expected))
        delivered = [value for f in futures for value in f.result(timeout=30)]
    source = b.admin.must("LRANGE", src, 0, -1)
    destination = b.admin.must("LRANGE", dst, 0, -1)
    assert len(delivered) == len(set(delivered)) == count, (name, "duplicate/missing delivery")
    assert set(delivered) == expected, (name, "wrong popped value")
    assert source == [] and len(destination) == count and set(destination) == expected, name
    print("PASS", name, left, to, "exact deliveries", count, "resumed", blocking, flush=True)


def pop(b, name, edge, count=2000):
    a, c = b.pair()
    expected = {str(i).encode() for i in range(count)}
    if name == "LMPOP":
        b.admin.must("RPUSH", a, *sorted(expected))
    else:
        b.admin.must("ZADD", a, *[v for i in range(count) for v in (i, str(i))])
    clients = [b.conn(timeout=30) for _ in range(4)]

    def worker(client):
        delivered = []
        # Concurrent probes may miss a key another owner-turn emptied. Every
        # non-null reply must correspond exactly to a live removal.
        while True:
            reply = client.must(name, 2, a, c, edge, "COUNT", 3)
            if reply is None:
                return delivered
            assert reply[0] in (a.encode(), c.encode()), reply
            delivered.extend(reply[1] if name == "LMPOP" else [v[0] for v in reply[1]])

    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        delivered = [v for result in pool.map(worker, clients) for v in result]
    assert len(delivered) == len(set(delivered)) == count and set(delivered) == expected, name
    assert b.admin.must("EXISTS", a, c) == 0, name
    print("PASS", name, edge, "exact live pops", count, flush=True)


def smove(b):
    clients = [b.conn(timeout=30) for _ in range(4)]
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        for _ in range(100):
            src, dst = b.pair()
            b.admin.must("SADD", src, "one")
            start = threading.Barrier(4)
            def worker(c):
                start.wait()
                return c.must("SMOVE", src, dst, "one")
            replies = list(pool.map(worker, clients))
            assert sorted(replies) == [0, 0, 0, 1], ("multiple SMOVE winners", replies)
            assert b.admin.must("SMEMBERS", src) == []
            assert b.admin.must("SMEMBERS", dst) == [b"one"]
    print("PASS SMOVE one actual removal, one winner in 100 races", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("port", type=int)
    parser.add_argument("--only")
    args = parser.parse_args()
    b = Battery(args)
    try:
        assert b.admin.must("CONFIG", "GET", "atomic")[1] == b"0"
        for name in ("RPOPLPUSH", "LMOVE", "BRPOPLPUSH", "BLMOVE", "LMPOP", "ZMPOP", "SMOVE"):
            if args.only and name not in args.only.split(","):
                continue
            if name in ("LMOVE", "BLMOVE"):
                for left in ("LEFT", "RIGHT"):
                    for to in ("LEFT", "RIGHT"):
                        move(b, name, left, to)
            elif name in ("RPOPLPUSH", "BRPOPLPUSH"):
                move(b, name)
            elif name in ("LMPOP", "ZMPOP"):
                for edge in (("LEFT", "RIGHT") if name == "LMPOP" else ("MIN", "MAX")):
                    pop(b, name, edge)
            else:
                smove(b)
    finally:
        b.close()


if __name__ == "__main__":
    main()
