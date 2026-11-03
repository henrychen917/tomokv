#!/usr/bin/env python3
"""RL5.1/RL5.2 live witnesses, derived from round5 T2/T10; gate owns every boot.

The linked production fixture supplies the exact held-owner/lane schedules.
These wire legs exercise CONFIG publication, both engines, and pipelined toggles.
An unopened SORT window rearms on fresh connections, bounded; it never passes.
"""
import argparse
import random
import select
import threading
import time

from _lib import Conn, encode, info


def expect(actual, wanted):
    assert actual == wanted, (actual, wanted)


def pair(host, port, avoid):
    pool = []
    by = {}
    for _ in range(64):
        c = Conn(host, port, buffering=0)
        tid = c.must("DEBUG", "IO-THREAD")
        pool.append(c)
        if tid != avoid and tid in by:
            keep = (by[tid], c)
            for p in pool:
                if p not in keep:
                    p.close()
            return keep
        by[tid] = c
    for c in pool:
        c.close()
    raise AssertionError("two connections on one non-owner IO not found")


def populate(c, big):
    rng = random.Random(11)
    for _ in range(20):
        commands = [("RPUSH", big, *[rng.randrange(1 << 40) for _ in range(1000)]) for _ in range(50)]
        c.raw(b"".join(encode(*cmd) for cmd in commands))
        for _ in commands:
            assert isinstance(c.read(), int)
    expect(c.cmd("LLEN", big), 1_000_000)


def monotonic(host, port, oracle=False):
    ctl = Conn(host, port)
    k, big, owner = "rlfix5:key", "rlfix5:sort", -1
    ctl.must("FLUSHALL")
    if not oracle:
        expect(info(ctl, "server")["read_local"], "1")
        owner = ctl.must("DEBUG", "SHARDS", k)[0][1]
        for i in range(10000):
            big = "rlfix5:sort:" + str(i)
            if ctl.must("DEBUG", "SHARDS", big)[0][1] == owner:
                break
        else:
            raise AssertionError("SORT key owner unavailable")
    populate(ctl, big)
    cases = (
        ("STRLEN", "v1", ("SET", k, "new-value"), ("STRLEN", k), 9, b"new-value"),
        ("EXISTS", None, ("SET", k, "created"), ("EXISTS", k), 1, b"created"),
        ("GETRANGE", "v1", ("SET", k, "v2"), ("GETRANGE", k, 0, -1), b"v2", b"v2"),
        ("TYPE", "v1", ("DEL", k), ("TYPE", k), b"none", None),
        ("TTL", "v1", ("DEL", k), ("TTL", k), -2, None),
        ("OBJECT", "v1", ("DEL", k), ("OBJECT", "ENCODING", k), None, None),
    )
    for name, initial, write, older, old_reply, get_reply in cases:
        witnessed = False
        for attempt in range(3):
            ctl.must("DEL", k)
            if initial is not None:
                ctl.must("SET", k, initial)
            c, writer = (Conn(host, port, buffering=0), Conn(host, port, buffering=0)) if oracle else pair(host, port, owner)
            blocker = Conn(host, port, buffering=0)
            try:
                blocker.send("SORT", big, "LIMIT", 0, 1)
                time.sleep(0.03)
                writer.send(*write)
                time.sleep(0.01)
                opened = not select.select([blocker.sock, writer.sock], [], [], 0)[0]
                c.raw(encode(*older) + encode("GET", k))
                actual = (c.read(), c.read())
                writer.read(); blocker.read()
                print(name, "attempt", attempt, "held-owner", opened, "replies", actual, flush=True)
                # Redis may choose either client's queued command first. Its pair must agree.
                if oracle:
                    previous = (len(initial), initial.encode()) if name == "STRLEN" else None
                    if name == "EXISTS": previous = (0, None)
                    if name == "GETRANGE": previous = (initial.encode(), initial.encode())
                    if name == "TYPE": previous = (b"string", initial.encode())
                    if name == "TTL": previous = (-1, initial.encode())
                    if name == "OBJECT": previous = (b"embstr", initial.encode())
                    assert actual in ((old_reply, get_reply), previous), actual
                    witnessed = True
                elif opened:
                    expect(actual, (old_reply, get_reply))
                    witnessed = True
                if witnessed:
                    break
            finally:
                c.close(); writer.close(); blocker.close()
        assert witnessed, name + ": owner window never opened on three fresh connections"
    ctl.close()


def toggles(host, port, direction, oracle=False):
    ctl = Conn(host, port)
    ctl.must("CONFIG", "SET", "latency-tracking", "no")
    c = Conn(host, port)
    k = "rlfix5:toggle"
    ctl.must("SET", k, "initial")
    before = int(info(ctl, "stats").get("read_local_hits", "0"))
    expect(c.cmd("GET", k), b"initial")
    if not oracle:
        assert int(info(ctl, "stats")["read_local_hits"]) > before, "lane never armed"
    start, end = ("yes", "no") if direction == "yes-no" else ("no", "yes")
    errors = []
    barrier = threading.Barrier(2)
    def toggle():
        other = Conn(host, port)
        try:
            for _ in range(32):
                other.must("CONFIG", "SET", "latency-tracking", start)
                barrier.wait(timeout=20)
                other.must("CONFIG", "SET", "latency-tracking", end)
                barrier.wait(timeout=20)
        except BaseException as exc:
            errors.append(exc); barrier.abort()
        finally:
            other.close()
    thread = threading.Thread(target=toggle)
    thread.start()
    previous = b"initial"
    completed = False
    try:
        for turn in range(32):
            cmds, expected = [], []
            for n in range(8):
                value = ("value:%d:%d" % (turn, n)).encode()
                cmds += [("GET", k), ("SET", k, value), ("GET", k), ("MGET", k)]
                expected += [previous, b"OK", value, [value]]
                previous = value
            barrier.wait(timeout=20)
            c.raw(b"".join(encode(*cmd) for cmd in cmds))
            expect([c.read() for _ in cmds], expected)
            barrier.wait(timeout=20)
        completed = True
    finally:
        if not completed:
            barrier.abort()
        thread.join(timeout=30)
        ctl.must("CONFIG", "SET", "latency-tracking", "no")
        c.close(); ctl.close()
    assert not thread.is_alive() and not errors, errors
    print("PASS", direction, "32 pipelined toggles, 1024 exact replies", flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("host"); p.add_argument("port", type=int)
    p.add_argument("--case", choices=("monotonic", "yes-no", "no-yes"), required=True)
    p.add_argument("--oracle", action="store_true")
    a = p.parse_args()
    if a.case == "monotonic": monotonic(a.host, a.port, a.oracle)
    else: toggles(a.host, a.port, a.case, a.oracle)
