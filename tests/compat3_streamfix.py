#!/usr/bin/env python3
"""Assigned Redis 7.4 stream roots, compared on every gate matrix leg."""
import time
from compat3_lib import equal, run, wire
from _lib import Conn, RespError, info


def entry(i, value=b"v"):
    return [f"{i}-0".encode(), [b"f", value]]


def add(c, key, count, start=1):
    for i in range(start, start + count):
        equal(c.cmd("XADD", key, f"{i}-0", "f", "v"), f"{i}-0".encode(), "append")


def parked(c, count):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if int(info(c, "clients")["blocked_clients"]) == count:
            return
        time.sleep(.002)
    equal(int(info(c, "clients")["blocked_clients"]), count, "waiter really registered")


def xread(c):
    out = []
    for resp in (2, 3):
        c.cmd("HELLO", resp)
        c.cmd("DEL", "a", "b", "empty", "absent", "wrong")
        add(c, "a", 3)
        add(c, "b", 2)
        c.cmd("XGROUP", "CREATE", "empty", "g", "0", "MKSTREAM")
        for args in (("STREAMS", "a", "+"), ("COUNT", 100, "STREAMS", "a", "+"),
                     ("BLOCK", 0, "STREAMS", "a", "+"),
                     ("STREAMS", "empty", "absent", "+", "+"),
                     ("STREAMS", "b", "a", "empty", "+", "+", "+"),
                     ("STREAMS", "a", "b", "+", "0"),
                     ("STREAMS", "a", "18446744073709551615-18446744073709551615")):
            got = c.cmd("XREAD", *args)
            assert not isinstance(got, RespError), got
            out.append(got)
        c.cmd("XDEL", "a", "3-0")
        got = c.cmd("XREAD", "STREAMS", "a", "+")
        equal(got, [[b"a", [entry(2)]]] if resp == 2 else [b"a", [entry(2)]], "last live ID")
        out.append(got)
        c.cmd("SET", "wrong", "value")
        out.append(wire(c.cmd("XREAD", "STREAMS", "a", "wrong", "+", "+")))
        # Fresh absent, MKSTREAM-empty, and all-deleted streams must actually block.
        for kind in ("absent", "empty", "deleted"):
            key = "wait:" + kind
            c.cmd("DEL", key)
            if kind == "empty": c.cmd("XGROUP", "CREATE", key, "g", "0", "MKSTREAM")
            if kind == "deleted":
                add(c, key, 1)
                c.cmd("XDEL", key, "1-0")
            waiter = Conn(c.host, c.port, timeout=4, buffering=0)
            try:
                waiter.cmd("HELLO", resp)
                waiter.send("XREAD", "COUNT", 100, "BLOCK", 0, "STREAMS", key, "+")
                parked(c, 1)
                c.cmd("XADD", key, "9-0", "f", "v")
                reply = waiter.read()
                equal(reply, [[key.encode(), [entry(9)]]] if resp == 2 else [key.encode(), [entry(9)]], "wake +")
                out.append(reply)
                parked(c, 0)
            finally:
                waiter.close()
        c.cmd("DEL", "timeout")
        out.append(c.cmd("XREAD", "BLOCK", 15, "STREAMS", "timeout", "+"))
    c.cmd("HELLO", 2)
    return out


def ranges(c):
    add(c, "s", 2)
    out = []
    for command, bounds in (("XRANGE", ("-", "+")), ("XREVRANGE", ("+", "-"))):
        for pos in (0, 1):
            for invalid in ("(-", "(+"):
                args = list(bounds); args[pos] = invalid
                result = c.cmd(command, "s", *args)
                equal(wire(result), {"error": b"ERR Invalid stream ID specified as stream command argument".hex()}, "exclusive sentinel")
                out.append(wire(result))
        for bounds in (("(1-0", "(2-0"), ("(0-0", "+"), ("-", "(0-0"),
                       ("(18446744073709551615-18446744073709551615", "+")):
            out.append(wire(c.cmd(command, "s", *bounds)))
    return out


def groupdash(c):
    add(c, "s", 3)
    equal(c.cmd("XGROUP", "CREATE", "s", "g", "$"), b"OK", "create group")
    out = []
    for cursor in ("-", "+", "0", "1-0", "(-", "(+", "01-0"):
        out.append(wire(c.cmd("XGROUP", "SETID", "s", "g", cursor)))
    equal(c.cmd("XGROUP", "SETID", "s", "g", "-"), b"OK", "rewind to sentinel")
    out.append(c.cmd("XREADGROUP", "GROUP", "g", "c1", "STREAMS", "s", ">"))
    out.append(c.cmd("XAUTOCLAIM", "s", "g", "c2", 0, "-", "COUNT", 1))
    equal(out[-1], [b"2-0", [entry(1)], []], "claim from sentinel")
    c.cmd("XDEL", "s", "2-0")
    out.append(c.cmd("XAUTOCLAIM", "s", "g", "c3", 0, "-", "COUNT", 2, "JUSTID"))
    out.append(c.cmd("XAUTOCLAIM", "s", "g", "c3", 0, "+", "COUNT", 2))
    return out


def claimcount(c):
    add(c, "s", 1)
    c.cmd("XGROUP", "CREATE", "s", "g", "0")
    out = []
    maximum = ((1 << 63) - 1) // 16
    for count in ("a", "", "01", "+1", "-0", "0", "-1", "1", str(maximum),
                  str(maximum + 1), "8070450532247928833", str((1 << 64) - 1), str(1 << 64)):
        result = c.cmd("XAUTOCLAIM", "s", "g", "c", 0, "3-0", "COUNT", count)
        if count not in ("1", str(maximum)):
            equal(wire(result), {"error": b"ERR COUNT must be > 0".hex()}, "COUNT range/grammar")
        elif count == str(maximum):
            equal(wire(result), {"error": b"ERR Insufficient memory, failed allocating transient memory, COUNT too high.".hex()}, "valid but unallocatable count")
        else:
            equal(result, [b"0-0", [], []], "valid count")
        out.append(wire(result))
    return out


def mpop(c):
    out = []
    for command in ("LMPOP", "ZMPOP", "BLMPOP", "BZMPOP"):
        block = command.startswith("B")
        zset = "ZMPOP" in command
        prefix = [command] + ([0] if block else [])
        edge = "MIN" if zset else "LEFT"
        for value in ("a", "", "0", "-1", "01", "+1", "-0", "9223372036854775808"):
            for args, label in (([value, "k", edge], "numkeys"), ([1, "k", edge, "COUNT", value], "count")):
                result = c.cmd(*prefix, *args)
                equal(wire(result), {"error": ("ERR " + label + " should be greater than 0").encode().hex()}, command + " " + label)
                out.append(wire(result))
        c.cmd("DEL", "k")
        if zset: c.cmd("ZADD", "k", 1, "a", 2, "b")
        else: c.cmd("RPUSH", "k", "a", "b")
        out.append(c.cmd(*prefix, 1, "k", edge, "COUNT", 1))
        c.cmd("DEL", "k")
        # Invalid COUNT must finish before blocking, even with an infinite timeout.
        if block: parked(c, 0)
    return out


def trimming(c):
    out = []
    # Every branch begins from a fresh stream. LIMIT=0 must differ from an omitted limit.
    for entries in (1, 2, 10, 100):
        c.cmd("CONFIG", "SET", "stream-node-max-entries", entries)
        c.cmd("CONFIG", "SET", "stream-node-max-bytes", 0)
        for strategy, threshold in (("MAXLEN", 2), ("MINID", "203-0")):
            for limit in (None, 0, 1, 2, 20):
                c.cmd("DEL", "trim")
                add(c, "trim", 205)
                args = [] if limit is None else ["LIMIT", limit]
                out.append(c.cmd("XTRIM", "trim", strategy, "~", threshold, *args))
                out.append(c.cmd("XRANGE", "trim", "-", "+"))
                out.append(c.cmd("XADD", "trim", strategy, "~", threshold, *args, "206-0", "f", "v"))
                out.append(c.cmd("XRANGE", "trim", "-", "+"))
        # Partial exact trimming and tombstones must not repack node boundaries.
        c.cmd("DEL", "trim")
        add(c, "trim", 205)
        out.append(c.cmd("XTRIM", "trim", "MAXLEN", "=", 166))
        out.append(c.cmd("XDEL", "trim", "41-0", "91-0", "202-0"))
        out.append(c.cmd("XTRIM", "trim", "MAXLEN", "~", 144))
        out.append(c.cmd("XRANGE", "trim", "-", "+"))
    # Byte thresholds use Redis's listpack sizing even with Compact storage. Include
    # changing dictionaries, integer/string boundaries, binary fields, and wide ID deltas.
    for byte_limit in (1, 64, 128, 512, 4096):
        c.cmd("CONFIG", "SET", "stream-node-max-entries", 0)
        c.cmd("CONFIG", "SET", "stream-node-max-bytes", byte_limit)
        for grouped in (False, True):
            c.cmd("DEL", "trim")
            if grouped: c.cmd("XGROUP", "CREATE", "trim", "g", "0", "MKSTREAM")
            for i in range(1, 81):
                fields = [b"f", str(i)] if i % 3 else [b"g\x00", b"00", b"f", b"x" * 65]
                ident = f"{i * 65536}-{i % 7}"
                equal(c.cmd("XADD", "trim", ident, *fields), ident.encode(), "byte-boundary append")
            out.append(c.cmd("XTRIM", "trim", "MAXLEN", "=", 71))
            out.append(c.cmd("XTRIM", "trim", "MAXLEN", "~", 43, "LIMIT", 0))
            out.append(c.cmd("XRANGE", "trim", "-", "+"))
    c.cmd("CONFIG", "SET", "stream-node-max-bytes", 0)
    c.cmd("CONFIG", "SET", "stream-node-max-entries", 2)
    c.cmd("DEL", "trim")
    add(c, "trim", 3)
    equal(c.cmd("XTRIM", "trim", "MAXLEN", "~", 0, "LIMIT", 1), 0, "LIMIT cannot split a node")
    equal(c.cmd("XLEN", "trim"), 3, "LIMIT leaves data")
    equal(c.cmd("XTRIM", "trim", "MAXLEN", "~", 0, "LIMIT", 2), 2, "whole-node LIMIT")
    c.cmd("CONFIG", "SET", "stream-node-max-entries", 1)
    c.cmd("DEL", "trim")
    add(c, "trim", 102)
    equal(c.cmd("XTRIM", "trim", "MAXLEN", "~", 1), 100, "default cap is 100 nodes")
    equal(c.cmd("XLEN", "trim"), 2, "default cap leaves last two")
    c.cmd("CONFIG", "SET", "stream-node-max-entries", 100)
    c.cmd("CONFIG", "SET", "stream-node-max-bytes", 4096)
    return out


def probe(c, case):
    return {"xread": xread, "ranges": ranges, "groupdash": groupdash,
            "claimcount": claimcount, "mpop": mpop, "trim": trimming}[case](c)


if __name__ == "__main__":
    run(probe, ("xread", "ranges", "groupdash", "claimcount", "mpop", "trim"))
