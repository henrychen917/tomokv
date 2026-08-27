#!/usr/bin/env python3
"""Directed hash-field TTL battery (HEXPIRE family).  Usage: tests/hexpire.py HOST PORT [MODE]

MODE (default "all"):
  all          the full in-process battery, including DEBUG RELOAD snapshot round-trip when the
               server was booted with --enable-debug-command local
  persistbuild seed state for an out-of-process restart (SAVE is left to the driver)
  persistcheck verify that state after the restart

Every check states BOTH quantities it compares.  The expiry checks are not allowed to pass just
because a reply looked plausible: each one reads INFO's expired_hash_fields / hash_field_expires
before and after and asserts the mechanism actually FIRED, with negative controls that assert those
same counters did NOT move when nothing should expire.
"""

import socket
import sys
import time

HOST = sys.argv[1]
PORT = int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "all"

FAILURES = []
CHECKS = [0]
EXPECT_DEFAULT = 206


def encode(*args):
    out = [b"*%d\r\n" % len(args)]
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out.append(b"$%d\r\n" % len(arg))
        out.append(arg)
        out.append(b"\r\n")
    return b"".join(out)


class Conn:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=20)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def raw(self, *args):
        """Reply as raw RESP bytes -- error strings are compared byte for byte."""
        self.sock.sendall(encode(*args))
        return self._read()

    def cmd(self, *args):
        return decode(self.raw(*args))

    def _read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed the connection")
        kind = line[:1]
        if kind in b"+-:":
            return line
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1:
                return line
            return line + self.file.read(size + 2)
        if kind == b"*":
            size = int(line[1:-2])
            if size == -1:
                return line
            return line + b"".join(self._read() for _ in range(size))
        raise AssertionError("unsupported RESP marker %r" % kind)


def decode(raw):
    kind = raw[:1]
    end = raw.index(b"\r\n")
    head = raw[1:end]
    if kind == b"+":
        return head.decode()
    if kind == b"-":
        return RuntimeError(head.decode())
    if kind == b":":
        return int(head)
    if kind == b"$":
        if int(head) == -1:
            return None
        return raw[end + 2:end + 2 + int(head)]
    if kind == b"*":
        rest = raw[end + 2:]
        out = []
        for _ in range(int(head)):
            consumed = reply_len(rest)
            out.append(decode(rest[:consumed]))
            rest = rest[consumed:]
        return out
    raise AssertionError("unsupported RESP marker %r" % kind)


def reply_len(raw):
    end = raw.index(b"\r\n")
    kind = raw[:1]
    if kind in b"+-:":
        return end + 2
    if kind == b"$":
        size = int(raw[1:end])
        return end + 2 if size == -1 else end + 2 + size + 2
    if kind == b"*":
        size = int(raw[1:end])
        total = end + 2
        for _ in range(max(size, 0)):
            total += reply_len(raw[total:])
        return total
    raise AssertionError("unsupported RESP marker %r" % kind)


def check(label, got, want):
    CHECKS[0] += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (label, got, want))


def check_true(label, condition, detail):
    CHECKS[0] += 1
    if not condition:
        FAILURES.append("%s: %s" % (label, detail))


def info_counter(conn, name):
    body = conn.cmd("INFO", "stats")
    if isinstance(body, bytes):
        for line in body.split(b"\r\n"):
            if line.startswith(name.encode() + b":"):
                return int(line.split(b":")[1])
    raise AssertionError("counter %s absent from INFO stats" % name)


# ---------------------------------------------------------------------------------------------
# 1. argument and error surface -- byte-exact against redis 7.4 (probed, then frozen here)
# ---------------------------------------------------------------------------------------------
def test_errors(c):
    c.cmd("FLUSHALL")
    c.cmd("HSET", "h", "a", "1", "b", "2")
    c.cmd("SET", "str", "v")
    wrongtype = b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n"
    numfields_mismatch = b"-ERR The `numfields` parameter must match the number of arguments\r\n"
    fields_missing = (b"-ERR Mandatory argument FIELDS is missing or not at the right position"
                      b"\r\n")
    write_numfields = b"-ERR Parameter `numFields` should be greater than 0\r\n"
    read_numfields = b"-ERR Number of fields must be a positive integer\r\n"

    for cmd in ("HEXPIRE", "HPEXPIRE", "HEXPIREAT", "HPEXPIREAT"):
        check("%s wrongtype" % cmd, c.raw(cmd, "str", "100", "FIELDS", "1", "a"), wrongtype)
        check("%s wrongtype outranks bad ttl" % cmd,
              c.raw(cmd, "str", "abc", "FIELDS", "1", "a"), wrongtype)
        check("%s bad ttl" % cmd, c.raw(cmd, "h", "abc", "FIELDS", "1", "a"),
              b"-ERR value is not an integer or out of range\r\n")
        check("%s negative ttl" % cmd, c.raw(cmd, "h", "-1", "FIELDS", "1", "a"),
              b"-ERR invalid expire time, must be >= 0\r\n")
        check("%s numfields mismatch" % cmd, c.raw(cmd, "h", "100", "FIELDS", "2", "a"),
              numfields_mismatch)
        check("%s numfields extra" % cmd, c.raw(cmd, "h", "100", "FIELDS", "1", "a", "b"),
              numfields_mismatch)
        check("%s numfields zero" % cmd, c.raw(cmd, "h", "100", "FIELDS", "0", "a"),
              write_numfields)
        check("%s numfields negative" % cmd, c.raw(cmd, "h", "100", "FIELDS", "-1", "a"),
              write_numfields)
        check("%s numfields not a number" % cmd, c.raw(cmd, "h", "100", "FIELDS", "x", "a"),
              write_numfields)
        check("%s FIELDS missing" % cmd, c.raw(cmd, "h", "100", "NOPE", "1", "a"), fields_missing)
        check("%s two conditions" % cmd, c.raw(cmd, "h", "100", "NX", "XX", "FIELDS", "1", "a"),
              fields_missing)

    for cmd in ("HTTL", "HPTTL", "HEXPIRETIME", "HPEXPIRETIME", "HPERSIST"):
        check("%s wrongtype" % cmd, c.raw(cmd, "str", "FIELDS", "1", "a"), wrongtype)
        check("%s numfields mismatch" % cmd, c.raw(cmd, "h", "FIELDS", "2", "a"),
              numfields_mismatch)
        check("%s numfields not a number" % cmd, c.raw(cmd, "h", "FIELDS", "x", "a"),
              read_numfields)
        check("%s numfields zero" % cmd, c.raw(cmd, "h", "FIELDS", "0", "a"), read_numfields)
        check("%s FIELDS missing" % cmd, c.raw(cmd, "h", "NOPE", "1", "a"), fields_missing)

    # the 46-bit deadline ceiling, on both the absolute and the relative form of each unit
    check("HPEXPIREAT ceiling accepted", c.cmd("HPEXPIREAT", "h", "70368744177663",
                                               "FIELDS", "1", "a"), [1])
    check("HPEXPIREAT above ceiling", c.raw("HPEXPIREAT", "h", "70368744177664",
                                            "FIELDS", "1", "a"),
          b"-ERR invalid expire time in 'hpexpireat' command\r\n")
    check("HEXPIREAT ceiling accepted", c.cmd("HEXPIREAT", "h", "70368744177",
                                              "FIELDS", "1", "a"), [1])
    check("HEXPIREAT above ceiling", c.raw("HEXPIREAT", "h", "70368744178",
                                           "FIELDS", "1", "a"),
          b"-ERR invalid expire time in 'hexpireat' command\r\n")
    check("HEXPIRE above ceiling", c.raw("HEXPIRE", "h", "1000000000000", "FIELDS", "1", "a"),
          b"-ERR invalid expire time in 'hexpire' command\r\n")
    check("HPEXPIRE above ceiling", c.raw("HPEXPIRE", "h", "70368744177664",
                                          "FIELDS", "1", "a"),
          b"-ERR invalid expire time in 'hpexpire' command\r\n")

    # arity is the registry's job; assert it is actually wired to the right minimum
    check("HEXPIRE arity", c.raw("HEXPIRE", "h", "100", "FIELDS", "1"),
          b"-ERR wrong number of arguments for 'hexpire' command\r\n")
    check("HTTL arity", c.raw("HTTL", "h", "FIELDS", "1"),
          b"-ERR wrong number of arguments for 'httl' command\r\n")

    # missing key answers -2 per field rather than erroring (redis 7.4.2 shape)
    check("HEXPIRE missing key", c.cmd("HEXPIRE", "nokey", "100", "FIELDS", "2", "a", "b"),
          [-2, -2])
    check("HTTL missing key", c.cmd("HTTL", "nokey", "FIELDS", "3", "a", "b", "c"), [-2, -2, -2])
    check("HPERSIST missing key", c.cmd("HPERSIST", "nokey", "FIELDS", "1", "a"), [-2])
    check("case-insensitive tokens", c.cmd("hexpire", "h", "100", "nx", "fields", "1", "b"), [1])


# ---------------------------------------------------------------------------------------------
# 2. NX/XX/GT/LT matrix, on all four setters, against both a TTL-free and a TTL-bearing field
# ---------------------------------------------------------------------------------------------
def test_conditions(c):
    c.cmd("FLUSHALL")
    far = int(time.time() * 1000) + 3600 * 1000

    def fresh(field="f", ttl=None):
        c.cmd("DEL", "k")
        c.cmd("HSET", "k", field, "v")
        if ttl is not None:
            check("setup ttl", c.cmd("HPEXPIREAT", "k", str(ttl), "FIELDS", "1", field), [1])

    # against a field with NO deadline: no-deadline is infinity
    for cond, want in (("NX", 1), ("XX", 0), ("GT", 0), ("LT", 1)):
        fresh()
        check("%s on ttl-free field" % cond,
              c.cmd("HEXPIRE", "k", "100", cond, "FIELDS", "1", "f"), [want])
        check("%s on ttl-free field effect" % cond,
              c.cmd("HTTL", "k", "FIELDS", "1", "f"), [100 if want else -1])

    # against a field WITH a deadline; compare a strictly larger and a strictly smaller proposal
    for cond, delta, want in (("NX", 1000, 0), ("XX", 1000, 1),
                              ("GT", 1000, 1), ("GT", -1000, 0), ("GT", 0, 0),
                              ("LT", -1000, 1), ("LT", 1000, 0), ("LT", 0, 0)):
        fresh(ttl=far)
        got = c.cmd("HPEXPIREAT", "k", str(far + delta), cond, "FIELDS", "1", "f")
        check("%s delta=%d on ttl field" % (cond, delta), got, [want])
        expected = far + delta if want else far
        check("%s delta=%d deadline" % (cond, delta),
              c.cmd("HPEXPIRETIME", "k", "FIELDS", "1", "f"), [expected])

    # a condition that is not met never deletes, even with an already-past deadline
    fresh(ttl=far)
    check("past+NX blocked by condition", c.cmd("HEXPIREAT", "k", "1", "NX", "FIELDS", "1", "f"),
          [0])
    check("past+NX left the field alone", c.cmd("HEXISTS", "k", "f"), 1)
    check("past+XX deletes", c.cmd("HEXPIREAT", "k", "1", "XX", "FIELDS", "1", "f"), [2])
    check("past+XX removed the field", c.cmd("EXISTS", "k"), 0)

    fresh()
    check("past+XX on ttl-free field blocked",
          c.cmd("HEXPIREAT", "k", "1", "XX", "FIELDS", "1", "f"), [0])
    check("past+GT on ttl-free field blocked",
          c.cmd("HEXPIREAT", "k", "1", "GT", "FIELDS", "1", "f"), [0])
    check("field survived blocked deletes", c.cmd("HEXISTS", "k", "f"), 1)
    check("past+LT on ttl-free field deletes",
          c.cmd("HEXPIREAT", "k", "1", "LT", "FIELDS", "1", "f"), [2])

    # mixed per-field results in one reply
    c.cmd("DEL", "m")
    c.cmd("HSET", "m", "a", "1", "b", "2", "c", "3")
    c.cmd("HPEXPIREAT", "m", str(far), "FIELDS", "1", "a")
    check("mixed results", c.cmd("HEXPIRE", "m", "100", "NX", "FIELDS", "4",
                                 "a", "b", "nosuch", "c"), [0, 1, -2, 1])
    # duplicate fields are processed independently, as in redis
    check("duplicate fields", c.cmd("HTTL", "m", "FIELDS", "2", "b", "b"), [100, 100])


# ---------------------------------------------------------------------------------------------
# 3. read family: value shapes, rounding, and HPERSIST
# ---------------------------------------------------------------------------------------------
def test_reads(c):
    c.cmd("FLUSHALL")
    c.cmd("HSET", "k", "a", "1", "b", "2")
    deadline = int(time.time() * 1000) + 100 * 1000 + 400
    check("set absolute deadline", c.cmd("HPEXPIREAT", "k", str(deadline), "FIELDS", "1", "a"), [1])
    check("HPEXPIRETIME is exact", c.cmd("HPEXPIRETIME", "k", "FIELDS", "1", "a"), [deadline])
    check("HEXPIRETIME rounds up", c.cmd("HEXPIRETIME", "k", "FIELDS", "1", "a"),
          [(deadline + 999) // 1000])
    pttl = c.cmd("HPTTL", "k", "FIELDS", "1", "a")[0]
    check_true("HPTTL in range", 99000 < pttl <= 100400,
               "HPTTL %d is outside (99000, 100400]" % pttl)
    ttl = c.cmd("HTTL", "k", "FIELDS", "1", "a")[0]
    check("HTTL is the ceiling of HPTTL", ttl, (pttl + 999) // 1000)

    check("read family: no ttl / no field", c.cmd("HTTL", "k", "FIELDS", "3", "a", "b", "zz"),
          [ttl, -1, -2])
    for cmd in ("HPTTL", "HEXPIRETIME", "HPEXPIRETIME"):
        got = c.cmd(cmd, "k", "FIELDS", "3", "a", "b", "zz")
        check("%s sentinels" % cmd, [got[1], got[2]], [-1, -2])

    check("HPERSIST codes", c.cmd("HPERSIST", "k", "FIELDS", "3", "a", "b", "zz"), [1, -1, -2])
    check("HPERSIST is idempotent", c.cmd("HPERSIST", "k", "FIELDS", "1", "a"), [-1])
    check("HTTL after HPERSIST", c.cmd("HTTL", "k", "FIELDS", "1", "a"), [-1])


# ---------------------------------------------------------------------------------------------
# 4. value writes clear a field TTL; counter writes keep it (redis 7.4)
# ---------------------------------------------------------------------------------------------
def test_write_interactions(c):
    c.cmd("FLUSHALL")
    c.cmd("HSET", "k", "a", "1", "n", "5")
    c.cmd("HEXPIRE", "k", "100", "FIELDS", "2", "a", "n")

    check("HSET clears that field's ttl", [c.cmd("HSET", "k", "a", "2"),
                                           c.cmd("HTTL", "k", "FIELDS", "1", "a")], [0, [-1]])
    check("HSET left the other field's ttl", c.cmd("HTTL", "k", "FIELDS", "1", "n"), [100])
    check("HINCRBY keeps the ttl", [c.cmd("HINCRBY", "k", "n", "1"),
                                    c.cmd("HTTL", "k", "FIELDS", "1", "n")], [6, [100]])
    check("HINCRBYFLOAT keeps the ttl", c.cmd("HTTL", "k", "FIELDS", "1", "n"), [100])
    c.cmd("HINCRBYFLOAT", "k", "n", "0.5")
    check("HINCRBYFLOAT keeps the ttl (after)", c.cmd("HTTL", "k", "FIELDS", "1", "n"), [100])
    check("HSETNX on an existing ttl field is a no-op",
          [c.cmd("HSETNX", "k", "n", "0"), c.cmd("HTTL", "k", "FIELDS", "1", "n")], [0, [100]])

    # HMSET shares the handler; make sure the clearing runs on that entry point too
    c.cmd("HEXPIRE", "k", "100", "FIELDS", "1", "a")
    check("HMSET clears the ttl", [c.cmd("HMSET", "k", "a", "z"),
                                   c.cmd("HTTL", "k", "FIELDS", "1", "a")], ["OK", [-1]])

    # HDEL drops the field AND its deadline; re-adding the field must not resurrect one
    c.cmd("HEXPIRE", "k", "100", "FIELDS", "1", "n")
    c.cmd("HDEL", "k", "n")
    c.cmd("HSET", "k", "n", "5")
    check("re-added field has no ttl", c.cmd("HTTL", "k", "FIELDS", "1", "n"), [-1])

    # deleting the last TTL-bearing field with HDEL removes the key
    c.cmd("DEL", "solo")
    c.cmd("HSET", "solo", "f", "v")
    c.cmd("HEXPIRE", "solo", "100", "FIELDS", "1", "f")
    c.cmd("HDEL", "solo", "f")
    check("HDEL of the last field removed the key", c.cmd("EXISTS", "solo"), 0)


# ---------------------------------------------------------------------------------------------
# 5. past deadlines delete immediately; the last field takes the key with it
# ---------------------------------------------------------------------------------------------
def test_immediate_delete(c):
    c.cmd("FLUSHALL")
    c.cmd("HSET", "k", "a", "1", "b", "2", "c", "3")
    check("past deadline deletes", c.cmd("HEXPIREAT", "k", "1", "FIELDS", "2", "a", "b"), [2, 2])
    check("deleted fields are gone", c.cmd("HLEN", "k"), 1)
    check("past deadline on a missing field", c.cmd("HEXPIREAT", "k", "1", "FIELDS", "1", "zz"),
          [-2])
    check("last field takes the key", c.cmd("HEXPIREAT", "k", "1", "FIELDS", "1", "c"), [2])
    check("key gone", [c.cmd("EXISTS", "k"), c.cmd("HLEN", "k"), c.cmd("TYPE", "k")],
          [0, 0, "none"])
    # a deadline exactly equal to "now" counts as past
    now = int(time.time() * 1000)
    c.cmd("HSET", "e", "f", "v")
    check("deadline == now deletes", c.cmd("HPEXPIREAT", "e", str(now), "FIELDS", "1", "f"), [2])


# ---------------------------------------------------------------------------------------------
# 6. lazy expiry on access -- with the FIRED proof and its negative control
# ---------------------------------------------------------------------------------------------
def test_lazy_expiry(c):
    c.cmd("FLUSHALL")
    # negative control first: a hash with no field TTLs must not arm anything
    c.cmd("HSET", "plain", "a", "1", "b", "2")
    check("no ttls => nothing registered", info_counter(c, "hash_field_expires"), 0)
    before_plain = info_counter(c, "expired_hash_fields")
    for _ in range(50):
        c.cmd("HGETALL", "plain")
    check("TTL-free traffic expires nothing", info_counter(c, "expired_hash_fields"),
          before_plain)

    c.cmd("HSET", "k", "a", "1", "b", "2", "c", "3")
    check("HPEXPIRE armed", c.cmd("HPEXPIRE", "k", "250", "FIELDS", "2", "a", "b"), [1, 1])
    check_true("registration visible", info_counter(c, "hash_field_expires") >= 1,
               "hash_field_expires is 0 with a live field deadline")
    check("still present before the deadline", c.cmd("HLEN", "k"), 3)
    before = info_counter(c, "expired_hash_fields")
    time.sleep(0.45)

    # the first access is what reaps; every read must agree the fields are gone
    check("HGET filters", c.cmd("HGET", "k", "a"), None)
    check("HLEN filters", c.cmd("HLEN", "k"), 1)
    check("HEXISTS filters", c.cmd("HEXISTS", "k", "b"), 0)
    check("HSTRLEN filters", c.cmd("HSTRLEN", "k", "b"), 0)
    check("HMGET filters", c.cmd("HMGET", "k", "a", "b", "c"), [None, None, b"3"])
    check("HGETALL filters", sorted(c.cmd("HGETALL", "k")), [b"3", b"c"])
    check("HKEYS filters", c.cmd("HKEYS", "k"), [b"c"])
    check("HVALS filters", c.cmd("HVALS", "k"), [b"3"])
    check("HRANDFIELD filters", c.cmd("HRANDFIELD", "k", "-5"), [b"c"] * 5)
    check("HSCAN filters", c.cmd("HSCAN", "k", "0")[1], [b"c", b"3"])
    check("HTTL filters", c.cmd("HTTL", "k", "FIELDS", "2", "a", "b"), [-2, -2])

    after = info_counter(c, "expired_hash_fields")
    check("lazy reap FIRED (2 fields)", after - before, 2)

    # last live field expires -> the key itself goes on the next access
    c.cmd("DEL", "solo")
    c.cmd("HSET", "solo", "f", "v")
    c.cmd("HPEXPIRE", "solo", "200", "FIELDS", "1", "f")
    before = info_counter(c, "expired_hash_fields")
    time.sleep(0.4)
    check("lapsed hash reports empty", c.cmd("HLEN", "solo"), 0)
    check("lapsed hash is gone", [c.cmd("EXISTS", "solo"), c.cmd("TYPE", "solo")], [0, "none"])
    check("lazy key removal FIRED", info_counter(c, "expired_hash_fields") - before, 1)


# ---------------------------------------------------------------------------------------------
# 7. active expiry -- the key must vanish with NOBODY touching it
# ---------------------------------------------------------------------------------------------
def test_active_expiry(c):
    c.cmd("FLUSHALL")
    c.cmd("HSET", "act", "a", "1")
    c.cmd("HSET", "keep", "a", "1")
    check("active setup", c.cmd("HPEXPIRE", "act", "200", "FIELDS", "1", "a"), [1])
    before = info_counter(c, "expired_hash_fields")
    size_before = c.cmd("DBSIZE")
    # Nothing below reads "act": DBSIZE and INFO are keyspace-wide, so any removal is the ex
    # thread's own cycle rather than a lazy reap disguised as one.
    deadline = time.time() + 6.0
    while time.time() < deadline:
        time.sleep(0.25)
        if c.cmd("DBSIZE") < size_before:
            break
    check("active cycle removed the key without an access", c.cmd("DBSIZE"), size_before - 1)
    check_true("active reap FIRED", info_counter(c, "expired_hash_fields") > before,
               "expired_hash_fields did not move (was %d)" % before)
    check("the TTL-free hash was left alone", c.cmd("HGET", "keep", "a"), b"1")

    # negative control: a live deadline must NOT be collected while it is still in the future
    c.cmd("HSET", "future", "a", "1")
    c.cmd("HEXPIRE", "future", "600", "FIELDS", "1", "a")
    settled = info_counter(c, "expired_hash_fields")
    time.sleep(1.5)
    check("future deadline survives the cycle", info_counter(c, "expired_hash_fields"), settled)
    check("future field still readable", c.cmd("HGET", "future", "a"), b"1")


# ---------------------------------------------------------------------------------------------
# 8. representation coverage: embedded promotion, expanded hashes, wide TTL tables
# ---------------------------------------------------------------------------------------------
def test_representations(c):
    c.cmd("FLUSHALL")
    far = int(time.time() * 1000) + 3600 * 1000

    # an embedded (one-allocation) hash is externalized by its first field deadline
    c.cmd("HSET", "small", "f", "v")
    check("small hash starts listpack (redis encoding name)", c.cmd("OBJECT", "ENCODING", "small"), b"listpack")
    check("first deadline on a small hash", c.cmd("HEXPIRE", "small", "100", "FIELDS", "1", "f"),
          [1])
    check("value survives externalization", c.cmd("HGET", "small", "f"), b"v")
    check("deadline readable", c.cmd("HTTL", "small", "FIELDS", "1", "f"), [100])

    # HEXPIRE that sets nothing must not force the representation change
    c.cmd("HSET", "untouched", "f", "v")
    check("no such field", c.cmd("HEXPIRE", "untouched", "100", "FIELDS", "1", "zz"), [-2])
    check("condition not met", c.cmd("HEXPIRE", "untouched", "100", "XX", "FIELDS", "1", "f"), [0])
    check("still ttl-free", c.cmd("HTTL", "untouched", "FIELDS", "1", "f"), [-1])

    # expanded (hashtable) hash with deadlines on a subset
    args = []
    for i in range(600):
        args += ["f%d" % i, "v%d" % i]
    c.cmd("HSET", "big", *args)
    check("big hash promoted", c.cmd("OBJECT", "ENCODING", "big"), b"hashtable")
    picked = ["f%d" % i for i in range(0, 600, 3)]          # 200 fields
    got = c.cmd("HPEXPIREAT", "big", str(far), "FIELDS", str(len(picked)), *picked)
    check("wide deadline set", [len(got), set(got)], [200, {1}])
    check("wide deadline read back",
          c.cmd("HPEXPIRETIME", "big", "FIELDS", "3", "f0", "f3", "f1"), [far, far, -1])
    check("big hash still complete", c.cmd("HLEN", "big"), 600)
    # remove them all again: the table must collapse back to the unarmed state for this hash
    check("wide persist", set(c.cmd("HPERSIST", "big", "FIELDS", str(len(picked)), *picked)), {1})
    check("wide persist took", c.cmd("HTTL", "big", "FIELDS", "2", "f0", "f3"), [-1, -1])

    # binary and empty field names
    c.cmd("HSET", "bin", "a\x00b", "1", "", "2")
    check("binary field deadline", c.cmd("HPEXPIREAT", "bin", str(far), "FIELDS", "2",
                                         "a\x00b", ""), [1, 1])
    check("binary field readable", c.cmd("HPEXPIRETIME", "bin", "FIELDS", "2", "a\x00b", ""),
          [far, far])
    check("binary field persist", c.cmd("HPERSIST", "bin", "FIELDS", "1", "a\x00b"), [1])
    check("empty field keeps its deadline", c.cmd("HPEXPIRETIME", "bin", "FIELDS", "1", ""), [far])


# ---------------------------------------------------------------------------------------------
# 9. deadlines travel with the value: COPY / RENAME / DUMP+RESTORE, then a snapshot round-trip
# ---------------------------------------------------------------------------------------------
def test_value_transport(c):
    c.cmd("FLUSHALL")
    far = int(time.time() * 1000) + 3600 * 1000
    c.cmd("HSET", "src", "a", "1", "b", "2")
    c.cmd("HPEXPIREAT", "src", str(far), "FIELDS", "1", "a")

    check("COPY carries the deadline", [c.cmd("COPY", "src", "cp"),
                                        c.cmd("HPEXPIRETIME", "cp", "FIELDS", "2", "a", "b")],
          [1, [far, -1]])
    check("COPY made an independent table", c.cmd("HPERSIST", "cp", "FIELDS", "1", "a"), [1])
    check("source deadline untouched", c.cmd("HPEXPIRETIME", "src", "FIELDS", "1", "a"), [far])

    check("RENAME carries the deadline", [c.cmd("RENAME", "src", "ren"),
                                          c.cmd("HPEXPIRETIME", "ren", "FIELDS", "2", "a", "b")],
          ["OK", [far, -1]])

    # The redis-wire DUMP codec does not carry hash-field deadlines yet (redis 7.4's
    # RDB hash-TTL types are the queued breadth item), so a TTL-bearing hash must REFUSE
    # to serialize rather than silently drop deadlines. Snapshot transport is the proven
    # path (hexpire_persist.sh); this locks the cut visibly until the codec lands.
    blob = c.cmd("DUMP", "ren")
    check("DUMP of a TTL-bearing hash reports the codec cut",
          isinstance(blob, RuntimeError) and "could not be serialized" in str(blob), True)
    plain_blob = c.cmd("DUMP", "cp")  # cp's field TTL was HPERSISTed above: plain hash again
    check("DUMP of a TTL-free hash still serializes",
          isinstance(plain_blob, bytes) and len(plain_blob) > 10, True)
    check("RESTORE round-trips the TTL-free hash", [c.cmd("RESTORE", "rest", "0", plain_blob),
                                                    c.cmd("HGET", "rest", "a")],
          ["OK", c.cmd("HGET", "cp", "a")])

    reload_reply = c.cmd("DEBUG", "RELOAD")
    if isinstance(reload_reply, RuntimeError):
        FAILURES.append("DEBUG RELOAD required for snapshot round-trip: %s" % reload_reply)
        return
    check("snapshot round-trip keeps the deadline",
          c.cmd("HPEXPIRETIME", "ren", "FIELDS", "2", "a", "b"), [far, -1])
    check("snapshot round-trip keeps the values", sorted(c.cmd("HGETALL", "ren")),
          [b"1", b"2", b"a", b"b"])
    check_true("reloaded hash is re-registered", info_counter(c, "hash_field_expires") >= 1,
               "a reloaded field deadline left hash_field_expires at 0")

    # a field whose deadline is already past must not come back from the snapshot
    c.cmd("FLUSHALL")
    past = int(time.time() * 1000) + 500
    c.cmd("HSET", "mix", "gone", "1", "stays", "2")
    c.cmd("HPEXPIREAT", "mix", str(past), "FIELDS", "1", "gone")
    c.cmd("HSET", "allgone", "x", "1")
    c.cmd("HPEXPIREAT", "allgone", str(past), "FIELDS", "1", "x")
    c.cmd("DEBUG", "RELOAD")            # snapshot written while both deadlines are still ahead
    time.sleep(0.8)
    c.cmd("DEBUG", "RELOAD")            # ... and read back after they have passed
    check("lapsed field dropped on load", sorted(c.cmd("HGETALL", "mix")), [b"2", b"stays"])
    check("wholly lapsed hash absent after load", c.cmd("EXISTS", "allgone"), 0)


# ---------------------------------------------------------------------------------------------
# out-of-process restart phases (driver: tests/hexpire_persist.sh)
# ---------------------------------------------------------------------------------------------
PERSIST_DEADLINE = int(time.time() * 1000) + 24 * 3600 * 1000


def persist_build(c):
    c.cmd("FLUSHALL")
    far = PERSIST_DEADLINE
    c.cmd("HSET", "p:small", "a", "1", "b", "2")
    c.cmd("HPEXPIREAT", "p:small", str(far), "FIELDS", "1", "a")
    args = []
    for i in range(300):
        args += ["f%d" % i, "v%d" % i]
    c.cmd("HSET", "p:big", *args)
    picked = ["f%d" % i for i in range(0, 300, 5)]
    c.cmd("HPEXPIREAT", "p:big", str(far), "FIELDS", str(len(picked)), *picked)
    c.cmd("HSET", "p:none", "a", "1")
    check("build: small deadline", c.cmd("HPEXPIRETIME", "p:small", "FIELDS", "2", "a", "b"),
          [far, -1])
    print("  seeded p:small p:big p:none with deadline %d" % far)


def persist_check(c, far):
    check("restart: small deadline", c.cmd("HPEXPIRETIME", "p:small", "FIELDS", "2", "a", "b"),
          [far, -1])
    check("restart: small values", sorted(c.cmd("HGETALL", "p:small")),
          [b"1", b"2", b"a", b"b"])
    check("restart: big length", c.cmd("HLEN", "p:big"), 300)
    check("restart: big deadlines",
          c.cmd("HPEXPIRETIME", "p:big", "FIELDS", "3", "f0", "f5", "f1"), [far, far, -1])
    check("restart: ttl-free hash unchanged", c.cmd("HTTL", "p:none", "FIELDS", "1", "a"), [-1])
    check_true("restart: re-registered", info_counter(c, "hash_field_expires") >= 1,
               "hash_field_expires is 0 after a restart that restored field deadlines")


def main():
    c = Conn()
    if MODE == "persistbuild":
        persist_build(c)
        print("PERSIST_DEADLINE=%d" % PERSIST_DEADLINE)
    elif MODE.startswith("persistcheck"):
        persist_check(c, int(MODE.split(":", 1)[1]))
    else:
        for name, fn in (("errors", test_errors),
                         ("conditions", test_conditions),
                         ("reads", test_reads),
                         ("write-interactions", test_write_interactions),
                         ("immediate-delete", test_immediate_delete),
                         ("lazy-expiry", test_lazy_expiry),
                         ("active-expiry", test_active_expiry),
                         ("representations", test_representations),
                         ("value-transport", test_value_transport)):
            start = len(FAILURES)
            fn(c)
            print("  %-20s %s" % (name, "ok" if len(FAILURES) == start else "FAIL"))
        c.cmd("FLUSHALL")

    floor = EXPECT_DEFAULT if MODE == "all" else 0
    if CHECKS[0] < floor:
        FAILURES.append("executed-check floor: got %d, require >= %d" % (CHECKS[0], floor))

    count_text = "%d checks" % CHECKS[0]
    if floor:
        count_text += " (floor %d)" % floor
    if FAILURES:
        print("hexpire: %s, %d FAILURES" % (count_text, len(FAILURES)))
        for failure in FAILURES:
            print("  " + failure)
        sys.exit(1)
    print("hexpire: %s, 0 failures -> PASS" % count_text)


main()
