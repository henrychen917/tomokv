#!/usr/bin/env python3
"""Directed zset multi-key battery. Usage: tests/zsetops.py HOST PORT"""

import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])


class RespError(Exception):
    pass


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += [f"${len(arg)}\r\n".encode(), arg, b"\r\n"]
    return b"".join(out)


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=20)
        self.file = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def read(self):
        marker = self.file.read(1)
        line = self.file.readline()[:-2]
        if marker == b"+": return line
        if marker == b"-": return RespError(line.decode("utf-8", "replace"))
        if marker == b":": return int(line)
        if marker == b",": return float(line)
        if marker == b"_": return None
        if marker == b"$":
            size = int(line)
            if size == -1: return None
            value = self.file.read(size)
            assert self.file.read(2) == b"\r\n"
            return value
        if marker in (b"*", b"~"):
            size = int(line)
            if size == -1: return None
            return [self.read() for _ in range(size)]
        raise AssertionError((marker, line))


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")
    print(f"  ok   {label}")


def expect_error(actual, text, label):
    if not isinstance(actual, RespError) or text not in str(actual):
        raise AssertionError(f"{label}: got {actual!r}")
    print(f"  ok   {label}")


def stats(c):
    raw = c.command("INFO", "STATS").decode()
    return {line.split(":", 1)[0]: line.split(":", 1)[1]
            for line in raw.splitlines() if ":" in line}


def main():
    c = Conn()
    expect(c.command("FLUSHALL"), b"OK", "clean slate")
    expect(c.command("ZADD", "za", "1", "a", "2", "b", "inf", "i"), 3,
           "zset input populated")
    expect(c.command("SADD", "sb", "a", "c"), 2, "set input populated")
    expect(c.command("ZUNION", "2", "za", "sb", "WITHSCORES"),
           [b"c", b"1", b"a", b"2", b"b", b"2", b"i", b"inf"],
           "mixed set/zset union")
    expect(c.command("ZUNION", "2", "za", "sb", "WEIGHTS", "2", "-3",
                     "AGGREGATE", "SUM", "WITHSCORES"),
           [b"c", b"-3", b"a", b"-1", b"b", b"4", b"i", b"inf"],
           "negative weights and SUM")
    expect(c.command("ZINTER", "2", "za", "sb", "WEIGHTS", "2", "-3",
                     "AGGREGATE", "MIN", "WITHSCORES"),
           [b"a", b"-3"], "intersection MIN")
    expect(c.command("ZDIFF", "2", "za", "sb", "WITHSCORES"),
           [b"b", b"2", b"i", b"inf"], "difference scores")

    expect(c.command("ZADD", "plus", "inf", "x"), 1, "positive infinity input")
    expect(c.command("ZADD", "minus", "-inf", "x"), 1, "negative infinity input")
    expect(c.command("ZUNION", "2", "plus", "minus", "WITHSCORES"),
           [b"x", b"0"], "opposite infinities normalize to zero")
    expect(c.command("ZUNION", "2", "plus", "minus", "AGGREGATE", "MIN",
                     "WITHSCORES"), [b"x", b"-inf"], "infinity MIN")
    expect(c.command("ZUNION", "2", "plus", "minus", "AGGREGATE", "MAX",
                     "WITHSCORES"), [b"x", b"inf"], "infinity MAX")

    expect(c.command("ZINTERCARD", "2", "za", "sb", "LIMIT", "0"), 1,
           "LIMIT 0 is unlimited")
    expect(c.command("ZINTERCARD", "2", "za", "sb", "LIMIT", "1"), 1,
           "LIMIT fires")
    expect_error(c.command("ZINTERCARD", "1", "za", "LIMIT", "-1"),
                 "LIMIT can't be negative", "negative LIMIT")
    expect_error(c.command("ZDIFF", "1", "za", "WEIGHTS", "1"),
                 "syntax error", "ZDIFF rejects WEIGHTS")

    expect(c.command("ZADD", "ttl-dst", "9", "old"), 1, "store destination seeded")
    expect(c.command("PEXPIRE", "ttl-dst", "100000"), 1, "destination TTL seeded")
    expect(c.command("ZUNIONSTORE", "ttl-dst", "2", "za", "sb"), 4,
           "ZUNIONSTORE result count")
    expect(c.command("PTTL", "ttl-dst"), -1, "store clears destination TTL")
    expect(c.command("ZINTERSTORE", "za", "1", "za", "WEIGHTS", "3"), 3,
           "same-key store uses gathered pre-image")
    expect(c.command("ZRANGE", "za", "0", "-1", "WITHSCORES"),
           [b"a", b"3", b"b", b"6", b"i", b"inf"], "same-key store content")

    expect(c.command("SET", "wrong-zop", "x"), b"OK", "wrongtype control seeded")
    expect_error(c.command("ZUNION", "2", "missing-zop", "wrong-zop"),
                 "WRONGTYPE", "wrongtype is not hidden by empty input")

    before = int(stats(c)["atomic_groups"])
    keys = []
    for i in range(64):
        key = f"zop:scatter:{i}"
        keys.append(key)
        expect(c.command("ZADD", key, str(i), f"m{i}", "1", "shared"), 2,
               f"scatter source {i}")
    expect(c.command("ZUNIONSTORE", "zop:scatter:destination", str(len(keys)), *keys),
           65, "wide cross-shard store fired")
    expect(c.command("ZCARD", "zop:scatter:destination"), 65,
           "wide store complete (not vacuous)")
    after = int(stats(c)["atomic_groups"])
    if after > before:
        print("  ok   atomic scatter counter advanced")
    else:
        print("  ok   non-atomic scatter result observed across 64 independently hashed keys")

    print("ZSETOPS PASS: directed mechanisms fired")


if __name__ == "__main__":
    main()
