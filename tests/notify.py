#!/usr/bin/env python3
"""Directed Redis-compatible keyspace-notification test. Usage: notify.py HOST PORT"""

import select
import socket
import struct
import sys
import threading
import time


class RespError(Exception):
    pass


def encode(*args):
    out = [f"*{len(args)}\r\n".encode()]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.extend((f"${len(arg)}\r\n".encode(), arg, b"\r\n"))
    return b"".join(out)


class Conn:
    def __init__(self, host, port, timeout=10):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        # Unbuffered is intentional: drain()/receive() use select() to prove absence as well as
        # presence. A BufferedReader can hide a second already-read frame from the socket fd.
        self.file = self.sock.makefile("rb", buffering=0)

    def send(self, *args):
        self.sock.sendall(encode(*args))

    def command(self, *args):
        self.send(*args)
        return self.read()

    def exact(self, size):
        chunks = []
        while size:
            chunk = self.file.read(size)
            if not chunk:
                raise EOFError("server closed connection")
            chunks.append(chunk)
            size -= len(chunk)
        return b"".join(chunks)

    def read(self):
        prefix = self.exact(1)
        if not prefix:
            raise EOFError("server closed connection")
        line = self.file.readline()
        if not line.endswith(b"\r\n"):
            raise AssertionError(f"bad RESP line: {prefix + line!r}")
        value = line[:-2]
        if prefix == b"+":
            return value
        if prefix == b"-":
            return RespError(value.decode("utf-8", "replace"))
        if prefix == b":":
            return int(value)
        if prefix == b"$":
            size = int(value)
            if size == -1:
                return None
            payload = self.exact(size)
            assert self.exact(2) == b"\r\n"
            return payload
        if prefix == b"*":
            size = int(value)
            if size == -1:
                return None
            return [self.read() for _ in range(size)]
        raise AssertionError(f"unknown RESP prefix: {prefix!r}")

    def close(self, reset=False):
        if not self.sock:
            return
        if reset:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                 struct.pack("ii", 1, 0))
        self.file.close()
        self.sock.close()
        self.sock = None


def expect(actual, wanted, label):
    if actual != wanted:
        raise AssertionError(f"{label}: got {actual!r}, wanted {wanted!r}")


HOST = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 6379
admin = Conn(HOST, PORT)
driver = Conn(HOST, PORT)
listener = Conn(HOST, PORT)


def config(value):
    expect(admin.command("CONFIG", "SET", "notify-keyspace-events", value), b"OK",
           f"CONFIG SET {value!r}")


def config_get(name="notify-keyspace-events"):
    reply = admin.command("CONFIG", "GET", name)
    if not isinstance(reply, list) or len(reply) != 2:
        raise AssertionError(f"bad CONFIG GET {name}: {reply!r}")
    return reply[1].decode()


def info_stats():
    raw = admin.command("INFO", "STATS")
    result = {}
    for line in raw.decode().splitlines():
        if ":" not in line or line.startswith("#"):
            continue
        key, value = line.split(":", 1)
        try:
            result[key] = int(value)
        except ValueError:
            pass
    return result


def drain(quiet=0.08, limit=10000):
    frames = []
    deadline = time.monotonic() + quiet
    while len(frames) < limit:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([listener.sock], [], [], remaining)[0]:
            break
        frames.append(listener.read())
        deadline = time.monotonic() + quiet
    return frames


def receive(count, timeout=4):
    frames = []
    deadline = time.monotonic() + timeout
    while len(frames) < count:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([listener.sock], [], [], remaining)[0]:
            break
        frames.append(listener.read())
    if len(frames) != count:
        raise AssertionError(f"notification timeout: got {frames!r}, wanted {count} frames")
    return frames


def frame_event(frame):
    if len(frame) == 4 and frame[0] == b"pmessage":
        return frame[2].decode(), frame[3].decode()
    if len(frame) == 3 and frame[0] == b"message":
        return frame[1].decode(), frame[2].decode()
    raise AssertionError(f"bad notification frame: {frame!r}")


def setup(*commands):
    config("")
    drain()
    for command in commands:
        driver.command(*command)


def expect_e(flags, command, expected, label):
    config("E" + flags)
    drain()
    before = info_stats()["notify_events_fired"]
    reply = driver.command(*command)
    got = [frame_event(frame) for frame in receive(len(expected))]
    wanted = [(f"__keyevent@0__:{event}", key) for event, key in expected]
    expect(got, wanted, label)
    extra = drain()
    if extra:
        raise AssertionError(f"{label}: extra notifications {extra!r}")
    after = info_stats()["notify_events_fired"]
    expect(after - before, len(expected), f"{label} non-vacuous fired counter")
    return reply


def expect_none(flags, command, label):
    config(flags)
    drain()
    before = info_stats()["notify_events_fired"]
    driver.command(*command)
    expect(drain(0.15), [], label)
    expect(info_stats()["notify_events_fired"], before, f"{label} fired counter flat")


try:
    expect(admin.command("CONFIG", "SET", "atomic", "0"), b"OK", "initial atomic off")
    # G1-G4: exact parser, atomic rejection, normalization, and the upstream n-after-A arm.
    grammar = [
        ("", ""), ("KA", "AK"), ("EA", "AE"), ("gKE", "gKE"),
        ("$lshzxetKE", "$lshzxetKE"), ("gg", "g"), ("g$lshzxetd", "A"),
        ("AKEn", "AKEn"),
    ]
    for supplied, canonical in grammar:
        config(supplied)
        expect(config_get(), canonical, f"grammar {supplied!r}")
    for bad in ("Qz", "o", "c", "a", "S", "T", "I", "V", "r"):
        config("gKE")
        result = admin.command("CONFIG", "SET", "notify-keyspace-events", bad)
        if not isinstance(result, RespError) or "Invalid argument" not in str(result):
            raise AssertionError(f"bad flag {bad!r} accepted: {result!r}")
        expect(config_get(), "gKE", f"bad flag {bad!r} was atomic")

    config("")
    admin.command("FLUSHALL")
    listener.send("PSUBSCRIBE", "__keyspace@0__:*", "__keyevent@0__:*" )
    expect(listener.read(), [b"psubscribe", b"__keyspace@0__:*", 1], "subscribe K")
    expect(listener.read(), [b"psubscribe", b"__keyevent@0__:*", 2], "subscribe E")

    # M1-M4: route gating, K-before-E, and class gating.
    config("K$")
    driver.command("SET", "route:k", "v")
    expect([frame_event(x) for x in receive(1)],
           [("__keyspace@0__:route:k", "set")], "K only")
    config("E$")
    driver.command("SET", "route:e", "v")
    expect([frame_event(x) for x in receive(1)],
           [("__keyevent@0__:set", "route:e")], "E only")
    config("KE$")
    driver.command("SET", "route:both", "v")
    expect([frame_event(x) for x in receive(2)], [
        ("__keyspace@0__:route:both", "set"),
        ("__keyevent@0__:set", "route:both")], "K before E")
    expect_none("KE$", ("LPUSH", "route:list", "v"), "string class rejects list")
    expect_e("l", ("LPUSH", "route:list2", "v"), [("lpush", "route:list2")],
             "list class")

    # String and generic command rows, including multi-event source ordering.
    setup()
    expect_e("$", ("SET", "str:set", "v"), [("set", "str:set")], "SET")
    expect_e("$g", ("SET", "str:ttl", "v", "EX", "10"),
             [("set", "str:ttl"), ("expire", "str:ttl")], "SET EX")
    expect_e("g", ("SET", "str:past", "v", "PXAT", "1"),
             [("del", "str:past")], "SET past")
    expect_e("$", ("SETNX", "str:nx", "v"), [("set", "str:nx")], "SETNX")
    expect_none("E$", ("SETNX", "str:nx", "w"), "SETNX no-op")
    expect_e("$g", ("SETEX", "str:setex", "30", "v"),
             [("set", "str:setex"), ("expire", "str:setex")], "SETEX")
    expect_e("$g", ("PSETEX", "str:psetex", "30000", "v"),
             [("set", "str:psetex"), ("expire", "str:psetex")], "PSETEX")
    expect_e("$", ("GETSET", "str:getset", "v"), [("set", "str:getset")], "GETSET")
    expect_e("$", ("SETRANGE", "str:range", "2", "x"),
             [("setrange", "str:range")], "SETRANGE")
    expect_e("$", ("APPEND", "str:append", "x"), [("append", "str:append")], "APPEND")
    for command in ("INCR", "DECR"):
        setup(("SET", "str:counter", "5"))
        expect_e("$", (command, "str:counter"), [("incrby", "str:counter")], command)
    for command, amount in (("INCRBY", "3"), ("DECRBY", "2")):
        setup(("SET", f"str:{command.lower()}", "5"))
        key = f"str:{command.lower()}"
        expect_e("$", (command, key, amount), [("incrby", key)], command)
    expect_e("$", ("INCRBYFLOAT", "str:float", "1.25"),
             [("incrbyfloat", "str:float")], "INCRBYFLOAT")
    expect_e("$", ("SETBIT", "str:bit", "3", "1"), [("setbit", "str:bit")], "SETBIT")
    expect_e("$", ("PFADD", "str:hll", "a"), [("pfadd", "str:hll")], "PFADD")
    setup(("PFADD", "str:hll:source", "a"))
    expect_e("$", ("PFMERGE", "str:hll:dest", "str:hll:source"),
             [("pfadd", "str:hll:dest")], "PFMERGE")

    setup(("SET", "gen:del", "v"), ("SET", "gen:getdel", "v"),
          ("SET", "gen:ttl", "v", "EX", "100"))
    expect_e("g", ("DEL", "gen:del"), [("del", "gen:del")], "DEL")
    setup(("SET", "gen:unlink", "v"))
    expect_e("g", ("UNLINK", "gen:unlink"), [("del", "gen:unlink")], "UNLINK")
    expect_e("g", ("GETDEL", "gen:getdel"), [("del", "gen:getdel")], "GETDEL")
    expect_e("g", ("GETEX", "gen:ttl", "PERSIST"), [("persist", "gen:ttl")], "GETEX PERSIST")
    expect_e("g", ("GETEX", "gen:ttl", "EX", "100"), [("expire", "gen:ttl")], "GETEX EX")
    for command, deadline in (("EXPIRE", "100"), ("PEXPIRE", "100000"),
                              ("EXPIREAT", str(int(time.time()) + 100)),
                              ("PEXPIREAT", str(int(time.time() * 1000) + 100000))):
        key = f"gen:{command.lower()}"
        setup(("SET", key, "v"))
        expect_e("g", (command, key, deadline), [("expire", key)], command)
    setup(("SET", "gen:past-expire", "v"))
    expect_e("g", ("PEXPIREAT", "gen:past-expire", "1"),
             [("del", "gen:past-expire")], "PEXPIREAT past")
    setup(("SET", "gen:ttl", "v", "EX", "100"))
    expect_e("g", ("PERSIST", "gen:ttl"), [("persist", "gen:ttl")], "PERSIST")

    # Collection rows and shared del-on-empty ordering.
    setup(("RPUSH", "list:pop", "v"), ("RPUSH", "list:rem", "x"),
          ("RPUSH", "list:trim", "a", "b"), ("RPUSH", "list:set", "a"),
          ("RPUSH", "list:insert", "a", "b"))
    expect_e("l", ("LPUSH", "list:lpush", "v"), [("lpush", "list:lpush")], "LPUSH")
    expect_e("l", ("RPUSH", "list:rpush", "v"), [("rpush", "list:rpush")], "RPUSH")
    setup(("RPUSH", "list:lpushx", "seed"), ("LPUSH", "list:rpushx", "seed"))
    expect_e("l", ("LPUSHX", "list:lpushx", "v"), [("lpush", "list:lpushx")], "LPUSHX")
    expect_e("l", ("RPUSHX", "list:rpushx", "v"), [("rpush", "list:rpushx")], "RPUSHX")
    expect_e("lg", ("LPOP", "list:pop"), [("lpop", "list:pop"), ("del", "list:pop")], "LPOP del")
    setup(("RPUSH", "list:rpop", "v"))
    expect_e("lg", ("RPOP", "list:rpop"), [("rpop", "list:rpop"), ("del", "list:rpop")], "RPOP del")
    expect_e("lg", ("LREM", "list:rem", "0", "x"), [("lrem", "list:rem"), ("del", "list:rem")], "LREM del")
    expect_e("lg", ("LTRIM", "list:trim", "3", "1"), [("ltrim", "list:trim"), ("del", "list:trim")], "LTRIM del")
    expect_e("l", ("LSET", "list:set", "0", "z"), [("lset", "list:set")], "LSET")
    expect_e("l", ("LINSERT", "list:insert", "BEFORE", "b", "z"),
             [("linsert", "list:insert")], "LINSERT")

    setup(("SADD", "set:rem", "m"), ("SADD", "set:pop", "m"))
    expect_e("s", ("SADD", "set:add", "m"), [("sadd", "set:add")], "SADD")
    expect_e("sg", ("SREM", "set:rem", "m"), [("srem", "set:rem"), ("del", "set:rem")], "SREM del")
    expect_e("sg", ("SPOP", "set:pop"), [("spop", "set:pop"), ("del", "set:pop")], "SPOP del")
    setup(("HSET", "hash:del", "f", "v"))
    expect_e("hg", ("HDEL", "hash:del", "f"), [("hdel", "hash:del"), ("del", "hash:del")], "HDEL del")
    expect_e("h", ("HSET", "hash:set", "a", "1", "b", "2"), [("hset", "hash:set")], "HSET once")
    expect_e("h", ("HMSET", "hash:hmset", "a", "1", "b", "2"),
             [("hset", "hash:hmset")], "HMSET once")
    expect_e("h", ("HSETNX", "hash:setnx", "f", "v"),
             [("hset", "hash:setnx")], "HSETNX")
    expect_e("h", ("HINCRBY", "hash:incr", "f", "2"), [("hincrby", "hash:incr")], "HINCRBY")
    expect_e("h", ("HINCRBYFLOAT", "hash:float", "f", "2.5"),
             [("hincrbyfloat", "hash:float")], "HINCRBYFLOAT")

    setup(("ZADD", "z:rem", "1", "m"), ("ZADD", "z:range", "1", "a", "2", "b"),
          ("ZADD", "z:pop", "1", "m"))
    expect_e("zg", ("ZREM", "z:rem", "m"), [("zrem", "z:rem"), ("del", "z:rem")], "ZREM del")
    expect_e("zg", ("ZREMRANGEBYSCORE", "z:range", "-inf", "+inf"),
             [("zremrangebyscore", "z:range"), ("del", "z:range")], "ZREMRANGEBYSCORE")
    setup(("ZADD", "z:rank", "1", "a"), ("ZADD", "z:lex", "1", "a"))
    expect_e("zg", ("ZREMRANGEBYRANK", "z:rank", "0", "-1"),
             [("zremrangebyrank", "z:rank"), ("del", "z:rank")], "ZREMRANGEBYRANK")
    expect_e("zg", ("ZREMRANGEBYLEX", "z:lex", "-", "+"),
             [("zremrangebylex", "z:lex"), ("del", "z:lex")], "ZREMRANGEBYLEX")
    expect_e("zg", ("ZPOPMIN", "z:pop"), [("zpopmin", "z:pop"), ("del", "z:pop")], "ZPOPMIN")
    setup(("ZADD", "z:popmax", "1", "m"))
    expect_e("zg", ("ZPOPMAX", "z:popmax"),
             [("zpopmax", "z:popmax"), ("del", "z:popmax")], "ZPOPMAX")
    expect_e("z", ("ZADD", "z:add:plain", "1", "m"), [("zadd", "z:add:plain")], "ZADD")
    expect_e("z", ("ZADD", "z:add", "INCR", "1", "m"), [("zincr", "z:add")], "ZADD INCR")
    expect_e("z", ("ZINCRBY", "z:zincrby", "1", "m"), [("zincr", "z:zincrby")], "ZINCRBY")

    setup(("XADD", "stream:mutate", "1-0", "f", "v"),
          ("XADD", "stream:trim", "1-0", "f", "v"),
          ("XADD", "stream:trim", "2-0", "f", "w"))
    expect_e("t", ("XADD", "stream:add", "1-0", "f", "v"),
             [("xadd", "stream:add")], "XADD")
    expect_e("t", ("XDEL", "stream:mutate", "1-0"),
             [("xdel", "stream:mutate")], "XDEL")
    expect_none("Et", ("XDEL", "stream:mutate", "1-0"), "XDEL no-op")
    expect_e("t", ("XTRIM", "stream:trim", "MAXLEN", "=", "1"),
             [("xtrim", "stream:trim")], "XTRIM")

    # Cross-shard/store rows. Randomly seeded routing makes these names overwhelmingly split;
    # the same assertions also cover the local fast path when a pair happens to collide.
    setup(("SET", "cross:rename:a", "v"), ("SADD", "cross:set:a", "m"),
          ("LPUSH", "cross:list:a", "m"))
    expect_e("g", ("RENAME", "cross:rename:a", "cross:rename:z"),
             [("rename_from", "cross:rename:a"), ("rename_to", "cross:rename:z")], "RENAME")
    setup(("SET", "cross:renamenx:a", "v"))
    expect_e("g", ("RENAMENX", "cross:renamenx:a", "cross:renamenx:z"),
             [("rename_from", "cross:renamenx:a"),
              ("rename_to", "cross:renamenx:z")], "RENAMENX")
    setup(("SET", "cross:copy:a", "v"))
    expect_e("g", ("COPY", "cross:copy:a", "cross:copy:z"),
             [("copy_to", "cross:copy:z")], "COPY")
    expect_e("sg", ("SMOVE", "cross:set:a", "cross:set:z", "m"),
             [("srem", "cross:set:a"), ("del", "cross:set:a"),
              ("sadd", "cross:set:z")], "SMOVE")
    expect_e("lg", ("LMOVE", "cross:list:a", "cross:list:z", "LEFT", "RIGHT"),
             [("lpop", "cross:list:a"), ("del", "cross:list:a"),
              ("rpush", "cross:list:z")], "LMOVE")
    setup(("RPUSH", "cross:rpoplpush:a", "m"))
    expect_e("lg", ("RPOPLPUSH", "cross:rpoplpush:a", "cross:rpoplpush:z"),
             [("rpop", "cross:rpoplpush:a"), ("del", "cross:rpoplpush:a"),
              ("lpush", "cross:rpoplpush:z")], "RPOPLPUSH")
    setup(("RPUSH", "cross:lmpop", "a", "b"))
    expect_e("lg", ("LMPOP", "1", "cross:lmpop", "LEFT", "COUNT", "2"),
             [("lpop", "cross:lmpop"), ("del", "cross:lmpop")], "LMPOP")
    expect_e("$", ("MSET", "cross:mset:a", "1", "cross:mset:z", "2"),
             [("set", "cross:mset:a"), ("set", "cross:mset:z")], "MSET per key")
    expect_e("$", ("MSETNX", "cross:msetnx:a", "1", "cross:msetnx:z", "2"),
             [("set", "cross:msetnx:a"), ("set", "cross:msetnx:z")], "MSETNX per key")
    setup(("SET", "store:bit:a", "x"), ("SET", "store:bit:z", "y"))
    expect_e("$", ("BITOP", "OR", "store:bit:nonempty", "store:bit:a", "store:bit:z"),
             [("set", "store:bit:nonempty")], "BITOP non-empty")
    expect_e("g", ("BITOP", "AND", "store:bit", "none:a", "none:z"),
             [("del", "store:bit")], "BITOP empty")
    setup(("SADD", "store:set:a", "m"), ("SADD", "store:set:z", "m", "n"))
    expect_e("s", ("SINTERSTORE", "store:sinter", "store:set:a", "store:set:z"),
             [("sinterstore", "store:sinter")], "SINTERSTORE non-empty")
    expect_e("s", ("SUNIONSTORE", "store:sunion", "store:set:a", "store:set:z"),
             [("sunionstore", "store:sunion")], "SUNIONSTORE non-empty")
    expect_e("s", ("SDIFFSTORE", "store:sdiff", "store:set:z", "store:set:a"),
             [("sdiffstore", "store:sdiff")], "SDIFFSTORE non-empty")
    expect_e("g", ("SINTERSTORE", "store:set", "none:a", "none:z"),
             [("del", "store:set")], "SINTERSTORE empty")
    expect_e("g", ("SUNIONSTORE", "store:sunion:empty", "none:a", "none:z"),
             [("del", "store:sunion:empty")], "SUNIONSTORE empty")
    expect_e("g", ("SDIFFSTORE", "store:sdiff:empty", "none:a", "none:z"),
             [("del", "store:sdiff:empty")], "SDIFFSTORE empty")
    expect_e("g", ("ZRANGESTORE", "store:z", "none:z", "0", "-1"),
             [("del", "store:z")], "ZRANGESTORE empty")
    setup(("ZADD", "store:z:source", "1", "m"))
    expect_e("z", ("ZRANGESTORE", "store:z:dest", "store:z:source", "0", "-1"),
             [("zrangestore", "store:z:dest")], "ZRANGESTORE non-empty")
    setup(("RPUSH", "store:sort:source", "2", "1"))
    expect_e("l", ("SORT", "store:sort:source", "STORE", "store:sort:dest"),
             [("sortstore", "store:sort:dest")], "SORT STORE non-empty")
    expect_e("g", ("SORT", "none:sort", "STORE", "store:sort:empty"),
             [("del", "store:sort:empty")], "SORT STORE empty")

    setup(("ZADD", "cross:zmpop", "1", "a", "2", "b"))
    expect_e("zg", ("ZMPOP", "1", "cross:zmpop", "MAX", "COUNT", "2"),
             [("zpopmax", "cross:zmpop"), ("del", "cross:zmpop")], "ZMPOP")

    # Blocking commands fire at the actual owner-side pop, even on their immediate-ready path.
    setup(("RPUSH", "blocking:list", "v"), ("ZADD", "blocking:z", "1", "m"))
    expect_e("lg", ("BLPOP", "blocking:list", "1"),
             [("lpop", "blocking:list"), ("del", "blocking:list")], "BLPOP")
    expect_e("zg", ("BZPOPMIN", "blocking:z", "1"),
             [("zpopmin", "blocking:z"), ("del", "blocking:z")], "BZPOPMIN")
    setup(("RPUSH", "blocking:rpop", "v"),
          ("RPUSH", "blocking:lmpop", "a", "b"),
          ("RPUSH", "blocking:move", "v"),
          ("RPUSH", "blocking:rpoplpush", "v"),
          ("ZADD", "blocking:zmax", "1", "m"),
          ("ZADD", "blocking:zmpop", "1", "m"))
    expect_e("lg", ("BRPOP", "blocking:rpop", "1"),
             [("rpop", "blocking:rpop"), ("del", "blocking:rpop")], "BRPOP")
    expect_e("lg", ("BLMPOP", "1", "1", "blocking:lmpop", "LEFT", "COUNT", "2"),
             [("lpop", "blocking:lmpop"), ("del", "blocking:lmpop")], "BLMPOP")
    expect_e("lg", ("BLMOVE", "blocking:move", "blocking:move:dest",
                     "RIGHT", "LEFT", "1"),
             [("rpop", "blocking:move"), ("del", "blocking:move"),
              ("lpush", "blocking:move:dest")], "BLMOVE")
    expect_e("lg", ("BRPOPLPUSH", "blocking:rpoplpush",
                     "blocking:rpoplpush:dest", "1"),
             [("rpop", "blocking:rpoplpush"), ("del", "blocking:rpoplpush"),
              ("lpush", "blocking:rpoplpush:dest")], "BRPOPLPUSH")
    expect_e("zg", ("BZPOPMAX", "blocking:zmax", "1"),
             [("zpopmax", "blocking:zmax"), ("del", "blocking:zmax")], "BZPOPMAX")
    expect_e("zg", ("BZMPOP", "1", "1", "blocking:zmpop", "MIN", "COUNT", "1"),
             [("zpopmin", "blocking:zmpop"), ("del", "blocking:zmpop")], "BZMPOP")

    # m/n are outside A; new precedes the type event, and write lookups suppress keymiss.
    setup()
    expect_none("EA", ("GET", "miss:a"), "A excludes keymiss")
    expect_e("Am", ("GET", "miss:m"), [("keymiss", "miss:m")], "readonly keymiss")
    expect_none("Em", ("SET", "miss:write", "v"), "write suppresses keymiss")
    expect_e("$n", ("SET", "new:key", "v"), [("new", "new:key"), ("set", "new:key")], "new before set")
    expect_e("$n", ("SET", "new:key", "w"), [("set", "new:key")], "overwrite not new")
    expect_e("ln", ("LPUSH", "new:list", "v"), [("new", "new:list"), ("lpush", "new:list")], "new before lpush")

    # Lazy/active expiry share the keyless copied-key lane.
    setup()
    config("Ex")
    drain()
    before = info_stats()["notify_events_fired"]
    driver.command("SET", "expire:active", "v", "PX", "40")
    got = frame_event(receive(1, 5)[0])
    expect(got, ("__keyevent@0__:expired", "expire:active"), "active expiry")
    if info_stats()["notify_events_fired"] <= before:
        raise AssertionError("active expiry fired counter did not advance")
    config("")
    driver.command("SET", "expire:lazy", "v", "PX", "20")
    config("Ex")
    time.sleep(0.025)
    driver.command("GET", "expire:lazy")
    expect(frame_event(receive(1, 5)[0]),
           ("__keyevent@0__:expired", "expire:lazy"), "lazy expiry")

    # Maxmemory eviction uses the same keyless copied-key lane with the e class/name.
    setup()
    payload = "x" * 1024
    for i in range(160):
        driver.command("SET", f"evict:seed:{i}", payload)
    admin.command("CONFIG", "SET", "maxmemory-policy", "allkeys-lru")
    admin.command("CONFIG", "SET", "maxmemory", "16384")
    config("Ee")
    drain()
    before_fired = info_stats()["notify_events_fired"]
    before_evicted = info_stats()["evicted_keys"]
    evicted_frames = []
    for i in range(64):
        driver.command("SET", f"evict:trigger:{i}", payload)
        evicted_frames.extend(drain(0.05))
        if evicted_frames:
            break
    if not evicted_frames:
        raise AssertionError("eviction produced no notification")
    for frame in evicted_frames:
        channel, _ = frame_event(frame)
        expect(channel, "__keyevent@0__:evicted", "evicted event name")
    stats = info_stats()
    if stats["evicted_keys"] <= before_evicted or stats["notify_events_fired"] <= before_fired:
        raise AssertionError("eviction counters did not advance")
    admin.command("CONFIG", "SET", "maxmemory", "0")

    # Lua redis.call uses the nested command's class/name while retiring on the parent EVAL Op.
    setup()
    expect_e("$", ("EVAL", "return redis.call('SET', KEYS[1], 'v')", "1", "lua:key"),
             [("set", "lua:key")], "Lua nested SET")

    # N1 and live disable: FLUSH emits nothing; a disabled feature leaves fired flat.
    setup(("SET", "flush:key", "v"))
    expect_none("EA", ("FLUSHALL",), "FLUSHALL silent")
    config("")
    drain()
    before = info_stats()["notify_events_fired"]
    driver.command("SET", "disabled:key", "v")
    expect(drain(0.15), [], "disabled no frames")
    expect(info_stats()["notify_events_fired"], before, "disabled fired flat")

    # N2: class and route are on, but the existing pub/sub gauges prove there are no receivers.
    listener.send("PUNSUBSCRIBE", "__keyspace@0__:*", "__keyevent@0__:*")
    listener.read(); listener.read()
    config("EA")
    before = info_stats()["notify_events_fired"]
    driver.command("SET", "nosub:key", "v")
    expect(info_stats()["notify_events_fired"], before, "zero-subscriber skip")
    listener.send("PSUBSCRIBE", "__keyspace@0__:*", "__keyevent@0__:*")
    listener.read(); listener.read()

    # B1: the shared special-state batch is capped even for a many-key scatter command.
    admin.command("CONFIG", "SET", "atomic", "0")
    setup()
    keys = [f"cap:{i}" for i in range(5000)]
    mset = ["MSET"]
    for key in keys:
        mset.extend((key, "v"))
    expect(driver.command(*mset), b"OK", "cap setup MSET")
    config("Eg")
    drain()
    cap_before = info_stats()
    expect(driver.command("DEL", *keys), 5000, "bounded DEL count")
    capped = drain(0.2, 2000)
    cap_after = info_stats()
    if not capped or len(capped) > 1024:
        raise AssertionError(f"bounded batch delivered {len(capped)} events")
    if cap_after["notify_events_dropped"] - cap_before["notify_events_dropped"] < 3976:
        raise AssertionError("bounded batch did not expose overflow drops")
    expect(cap_after["notify_events_fired"] - cap_before["notify_events_fired"],
           len(capped), "bounded batch fired matches delivery")

    # Notification-specific pub/sub churn: abrupt pattern subscribers race a write stream, then
    # every shared pub/sub gauge (including reserved notification chains) must return to zero.
    listener.send("PUNSUBSCRIBE", "__keyspace@0__:*", "__keyevent@0__:*")
    listener.read(); listener.read()
    config("E$")
    churn_before = info_stats()["notify_events_fired"]
    writer_errors = []

    def write_storm():
        conn = Conn(HOST, PORT)
        try:
            for i in range(1200):
                conn.command("SET", f"churn:{i % 64}", str(i))
                time.sleep(0.0004)
        except Exception as error:
            writer_errors.append(repr(error))
        finally:
            conn.close()

    writer = threading.Thread(target=write_storm)
    writer.start()
    for _ in range(320):
        churn = Conn(HOST, PORT)
        churn.send("PSUBSCRIBE", "__keyevent@0__:*")
        churn.read()
        time.sleep(0.0005)
        churn.close(reset=True)
    writer.join(20)
    if writer.is_alive() or writer_errors:
        raise AssertionError(f"notification churn writer failed: {writer_errors!r}")
    deadline = time.monotonic() + 10
    while True:
        stats = info_stats()
        gauges = [stats[name] for name in (
            "pubsub_channels", "pubsub_subscriptions", "pubsub_patterns",
            "pubsub_home_entries", "pubsub_inflight", "pubsub_pending_commands")]
        if not any(gauges):
            break
        if time.monotonic() >= deadline:
            raise AssertionError(f"notification churn gauges did not drain: {gauges!r}")
        time.sleep(0.02)
    if info_stats()["notify_events_fired"] <= churn_before:
        raise AssertionError("notification churn was vacuous")
    listener.send("PSUBSCRIBE", "__keyspace@0__:*", "__keyevent@0__:*")
    listener.read(); listener.read()

    # Both atomic knob settings must preserve cross-shard event semantics.
    for atomic in ("0", "1"):
        expect(admin.command("CONFIG", "SET", "atomic", atomic), b"OK", f"atomic {atomic}")
        setup()
        key_a, key_z = f"atomic:{atomic}:a", f"atomic:{atomic}:z"
        expect_e("$", ("MSET", key_a, "1", key_z, "2"),
                 [("set", key_a), ("set", key_z)],
                 f"atomic={atomic} MSET")
        expect_e("g", ("DEL", key_a, key_z), [("del", key_a), ("del", key_z)],
                 f"atomic={atomic} DEL")

    fired = info_stats()["notify_events_fired"]
    if fired <= 0:
        raise AssertionError("notify_events_fired stayed zero")
    print(f"notify: ok (notify_events_fired={fired})")
finally:
    try:
        config("")
        admin.command("CONFIG", "SET", "maxmemory", "0")
    except Exception:
        pass
    listener.close()
    driver.close()
    admin.close()
