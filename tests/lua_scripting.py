#!/usr/bin/env python3
"""Directed EVAL/EVALSHA/SCRIPT single-owner scripting gate.

Usage: python3 tests/lua_scripting.py <host> <port>
"""
import hashlib
import os
import socket
import sys


HOST, PORT = sys.argv[1], int(sys.argv[2])
PREFIX = "lua:test:%d" % os.getpid()
FAIL = 0


class RespError(RuntimeError):
    pass


def note(name, ok, extra=""):
    global FAIL
    print(("  ok   " if ok else "  FAIL ") + name + (" " + extra if extra else ""), flush=True)
    if not ok:
        FAIL += 1


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, int):
            arg = str(arg)
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=20)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind = line[:1]
        if kind == b"+": return line[1:-2]
        if kind == b"-": raise RespError(line[1:-2].decode(errors="replace"))
        if kind == b":": return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1: return None
            data = self.file.read(size)
            if self.file.read(2) != b"\r\n": raise ValueError("bad bulk")
            return data
        if kind == b"*":
            count = int(line[1:-2])
            return None if count == -1 else [self.read() for _ in range(count)]
        raise ValueError("bad RESP marker %r" % kind)

    def cmd(self, *args):
        self.sock.sendall(frame(*args))
        return self.read()


def error_of(client, *args):
    try:
        client.cmd(*args)
    except RespError as exc:
        return str(exc)
    return ""


c = Resp()
keys = [PREFIX + suffix for suffix in (":value", ":count", ":list", ":missing", ":atomic")]
try:
    c.cmd("DEL", *keys)

    status = c.cmd("EVAL", "return redis.call('SET',KEYS[1],ARGV[1])", 1, keys[0], "bulk")
    integer = c.cmd("EVAL", "return redis.call('INCR',KEYS[1])", 1, keys[1])
    bulk = c.cmd("EVAL", "return redis.call('GET',KEYS[1])", 1, keys[0])
    c.cmd("RPUSH", keys[2], "a", "b", "c")
    array = c.cmd("EVAL", "return redis.call('LRANGE',KEYS[1],0,-1)", 1, keys[2])
    nil = c.cmd("EVAL", "return redis.call('GET',KEYS[1])", 1, keys[3])
    note("EVAL status/int/bulk/array/nil conversions",
         status == b"OK" and integer == 1 and bulk == b"bulk" and
         array == [b"a", b"b", b"c"] and nil is None,
         "values=%r/%r/%r/%r/%r" % (status, integer, bulk, array, nil))

    source = "return {ARGV[1],42,false,{ok='nested'}}"
    sha = hashlib.sha1(source.encode()).hexdigest()
    first = c.cmd("EVAL", source, 0, "armed")
    exists = c.cmd("SCRIPT", "EXISTS", sha)
    replay = c.cmd("EVALSHA", sha, 0, "replayed")
    loaded_source = "return ARGV[1]"
    loaded_sha = c.cmd("SCRIPT", "LOAD", loaded_source)
    loaded = c.cmd("EVALSHA", loaded_sha, 0, "loaded")
    note("EVAL and SCRIPT LOAD arm EVALSHA cache",
         first == [b"armed", 42, None, b"nested"] and exists == [1] and
         replay == [b"replayed", 42, None, b"nested"] and loaded == b"loaded")

    anchor = PREFIX + ":route:0"
    candidate = PREFIX + ":route:1"
    declared_pair = c.cmd("EVAL", "return {KEYS[1],KEYS[2]}", 2, anchor, candidate)
    # The ordinary feature loop intentionally has no DEBUG surface. xscript.py owns the
    # non-vacuous geometry assertion; this arm protects the public compatibility behavior.
    note("two declared KEYS are accepted",
         declared_pair == [anchor.encode(), candidate.encode()], repr(declared_pair))

    runaway = error_of(c, "EVAL", "while true do end", 0)
    note("instruction hook aborts runaway script with BUSY", runaway.startswith("BUSY "), runaway)
    note("server remains responsive after hook abort", c.cmd("PING") == b"PONG")

    c.cmd("SET", keys[0], "not-a-list")
    propagated = error_of(c, "EVAL", "return redis.call('LPUSH',KEYS[1],'x')", 1, keys[0])
    undeclared = error_of(c, "EVAL", "return redis.call('GET',ARGV[1])", 0, keys[0])
    note("redis.call errors propagate", "WRONGTYPE" in propagated, propagated)
    note("redis.call rejects undeclared keys", "undeclared key" in undeclared, undeclared)

    # A FAILED ACTIVATION KEEPS ITS EFFECTS, IN BOTH ATOMIC MODES.
    #
    # This used to assert the opposite for `atomic 1`: an undo log restored the declared keys, and
    # that restore was the lost-write P0 (it republished a superseded value, or erased a key the
    # script had just created). Redis has never undone partial script effects, so the atomic mode
    # may not change what a failed activation leaves behind. tests/scriptatomic.py owns the full
    # arm set and the counter proof; these two lines keep the claim in the lane's own battery.
    for mode in ("0", "1"):
        c.cmd("CONFIG", "SET", "atomic", mode)
        c.cmd("SET", keys[4], "before")
        partial = error_of(c, "EVAL",
                           "redis.call('SET',KEYS[1],'partial'); error('boom')", 1, keys[4])
        partial_value = c.cmd("GET", keys[4])
        note("atomic %s retains partial effects (redis semantics)" % mode,
             "boom" in partial and partial_value == b"partial", "%r %r" % (partial, partial_value))

        c.cmd("SET", keys[4], "before")
        killed = error_of(c, "EVAL",
                          "redis.call('SET',KEYS[1],'after'); while true do end", 1, keys[4])
        killed_value = c.cmd("GET", keys[4])
        note("atomic %s retains effects of a killed script" % mode,
             killed.startswith("BUSY ") and killed_value == b"after",
             "%r %r" % (killed, killed_value))

    c.cmd("SCRIPT", "FLUSH")
    flushed = c.cmd("SCRIPT", "EXISTS", sha, loaded_sha)
    noscript = error_of(c, "EVALSHA", sha, 0)
    note("SCRIPT FLUSH clears cache", flushed == [0, 0] and noscript.startswith("NOSCRIPT "))
finally:
    try:
        c.cmd("CONFIG", "SET", "atomic", "0")
        c.cmd("DEL", *keys)
    except Exception:
        pass
    c.close()

print("LUA SCRIPTING: %d FAIL" % FAIL)
sys.exit(1 if FAIL else 0)
