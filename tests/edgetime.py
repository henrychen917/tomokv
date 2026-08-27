#!/usr/bin/env python3
"""Directed expiry-interaction battery. Usage: tests/edgetime.py HOST PORT [MODE]

MODE defaults to ``all``.  Extra modes, neither of them gate modes -- each reproduces a SHELVED
defect written up in NOTES-EDGETIME.md and exits 1 while that defect is present:
  ``repro-hop``        the cross-shard fan-out expiry straddle. Carries its own negative control
                       (same widened fan-out, deadline an hour out -> no tear).
  ``repro-randomkey``  RANDOMKEY answering nil while live keys exist, once elapsed-unreaped keys
                       inflate an owner's published count. Control: the same shape, no deadlines.
  ``persistbuild`` / ``persistcheck:<deadline_ms>``  the two halves driven by edgetime_persist.sh.

The server must be booted with ``--enable-debug-command yes``.  Lazy-expiry and WATCH cases run
with active expiry disabled so the key under test is still PHYSICALLY counted when the operation
runs -- otherwise the case proves nothing about lazy expiry.  ``expired_keys`` from INFO is the
mechanism detector: every lazy/active case asserts it moved by exactly the expected amount, and
TTL-free controls assert the same detector can report zero.
"""

import socket
import sys
import time


HOST = sys.argv[1]
PORT = int(sys.argv[2])
MODE = sys.argv[3] if len(sys.argv) > 3 else "all"
FAILURES = []
CHECKS = 0


def encode(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class RespError:
    def __init__(self, message):
        self.message = message

    def __eq__(self, other):
        return isinstance(other, RespError) and other.message == self.message

    def __repr__(self):
        return "RespError(%r)" % self.message


class Resp:
    def __init__(self):
        self.sock = socket.create_connection((HOST, PORT), timeout=20)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        self.file.close()
        self.sock.close()

    def raw(self, *args):
        self.sock.sendall(encode(*args))
        return self._read_raw()

    def cmd(self, *args):
        return decode(self.raw(*args))

    def pipeline(self, commands):
        self.sock.sendall(b"".join(encode(*command) for command in commands))
        return [decode(self._read_raw()) for _ in commands]

    def _read_raw(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed connection")
        kind = line[:1]
        if kind in b"+-:":
            return line
        if kind == b"$":
            length = int(line[1:-2])
            return line if length == -1 else line + self.file.read(length + 2)
        if kind == b"*":
            count = int(line[1:-2])
            return line if count == -1 else line + b"".join(self._read_raw() for _ in range(count))
        raise ValueError("unsupported RESP marker %r" % line[:20])


def decode(raw):
    kind = raw[:1]
    end = raw.index(b"\r\n")
    head = raw[1:end]
    if kind == b"+":
        return head
    if kind == b"-":
        return RespError(head.decode(errors="replace"))
    if kind == b":":
        return int(head)
    if kind == b"$":
        length = int(head)
        return None if length == -1 else raw[end + 2:end + 2 + length]
    if kind == b"*":
        count = int(head)
        if count == -1:
            return None
        rest = raw[end + 2:]
        values = []
        for _ in range(count):
            used = reply_length(rest)
            values.append(decode(rest[:used]))
            rest = rest[used:]
        return values
    raise ValueError("unsupported RESP marker %r" % kind)


def reply_length(raw):
    end = raw.index(b"\r\n")
    kind = raw[:1]
    if kind in b"+-:":
        return end + 2
    if kind == b"$":
        length = int(raw[1:end])
        return end + 2 if length == -1 else end + 2 + length + 2
    if kind == b"*":
        count = int(raw[1:end])
        total = end + 2
        for _ in range(max(count, 0)):
            total += reply_length(raw[total:])
        return total
    raise ValueError("unsupported RESP marker %r" % kind)


def check(label, got, want):
    global CHECKS
    CHECKS += 1
    if got != want:
        FAILURES.append("%s: got %r, want %r" % (label, got, want))


def check_true(label, condition, detail):
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILURES.append("%s: %s" % (label, detail))


def info_counter(conn, name):
    body = conn.cmd("INFO", "stats")
    if isinstance(body, bytes):
        prefix = name.encode() + b":"
        for line in body.split(b"\r\n"):
            if line.startswith(prefix):
                return int(line.split(b":", 1)[1])
    raise AssertionError("INFO counter %s is absent" % name)


def set_active(conn, enabled):
    check("DEBUG SET-ACTIVE-EXPIRE %d" % enabled,
          conn.cmd("DEBUG", "SET-ACTIVE-EXPIRE", str(enabled)), b"OK")


# --------------------------------------------------------------------------------------------
# TTL arithmetic and the EXPIRE / SET / GETEX option grammars.
# --------------------------------------------------------------------------------------------

def test_expire_options(conn):
    conn.cmd("FLUSHALL")
    future_ms = int(time.time() * 1000) + 30 * 24 * 60 * 60 * 1000
    future_s = future_ms // 1000

    # Every one of the four registry rows must admit a variadic option list, not stop at the
    # arity gate.  Redis folds repeated flags, so NX NX is a plain NX.
    for command, deadline in (("EXPIRE", "2592000"), ("PEXPIRE", "2592000000"),
                              ("EXPIREAT", str(future_s)), ("PEXPIREAT", str(future_ms))):
        conn.cmd("SET", "opt:" + command, "v")
        check(command + " duplicate NX", conn.cmd(command, "opt:" + command, deadline, "NX", "NX"), 1)

    key = "opt:matrix"
    for options, want in ((("XX", "XX"), 1), (("GT", "GT"), 1), (("LT", "LT"), 0),
                          (("XX", "GT"), 1), (("XX", "LT"), 0), (("NX", "NX", "NX"), 0)):
        conn.cmd("SET", key, "v")
        conn.cmd("PEXPIREAT", key, str(future_ms))
        check("PEXPIREAT %s" % " ".join(options),
              conn.cmd("PEXPIREAT", key, str(future_ms + 1000), *options), want)

    incompatible_nx = b"-ERR NX and XX, GT or LT options at the same time are not compatible\r\n"
    incompatible_gt = b"-ERR GT and LT options at the same time are not compatible\r\n"
    for options in (("NX", "XX"), ("NX", "GT"), ("NX", "LT"), ("NX", "NX", "XX")):
        check("incompatible %s" % " ".join(options),
              conn.raw("PEXPIREAT", key, str(future_ms), *options), incompatible_nx)
    for options in (("GT", "LT"), ("GT", "GT", "LT"), ("XX", "GT", "LT")):
        check("incompatible %s" % " ".join(options),
              conn.raw("PEXPIREAT", key, str(future_ms), *options), incompatible_gt)

    # An unrecognised token is reported before either compatibility rule and before the deadline
    # is even parsed, echoed with its original case.
    check("unknown option preserves case",
          conn.raw("PEXPIREAT", key, str(future_ms), "NX", "bOgUs"),
          b"-ERR Unsupported option bOgUs\r\n")
    check("unknown option beats incompatibility",
          conn.raw("PEXPIREAT", key, str(future_ms), "NX", "XX", "BOGUS"),
          b"-ERR Unsupported option BOGUS\r\n")
    check("unknown option beats bad deadline",
          conn.raw("PEXPIREAT", key, "not-a-number", "BOGUS"),
          b"-ERR Unsupported option BOGUS\r\n")
    check("empty option echoes empty",
          conn.raw("PEXPIREAT", key, str(future_ms), b""),
          b"-ERR Unsupported option \r\n")
    # The echoed token must not be able to reach the reply framing.  Redis prints it as a C string
    # with CR/LF folded to spaces; anything else lets a client inject a second reply line.
    check("unknown option stops at NUL",
          conn.raw("PEXPIREAT", key, str(future_ms), b"bad\x00tail"),
          b"-ERR Unsupported option bad\r\n")
    check("unknown option folds LF",
          conn.raw("PEXPIREAT", key, str(future_ms), b"ba\nd"),
          b"-ERR Unsupported option ba d\r\n")
    check("unknown option folds CRLF",
          conn.raw("PEXPIREAT", key, str(future_ms), b"ba\r\n+PWNED"),
          b"-ERR Unsupported option ba  +PWNED\r\n")

    # A non-numeric deadline is "not an integer"; a numeric one that cannot be represented is
    # "invalid expire time".  Reporting the second for both is the divergence this row guards.
    not_integer = b"-ERR value is not an integer or out of range\r\n"
    conn.cmd("SET", "arith", "v")
    check("EXPIRE non-numeric", conn.raw("EXPIRE", "arith", "abc"), not_integer)
    check("EXPIRE non-numeric with option", conn.raw("EXPIRE", "arith", "abc", "NX"), not_integer)
    check("PEXPIREAT non-numeric", conn.raw("PEXPIREAT", "arith", "abc"), not_integer)
    check("SET EX non-numeric", conn.raw("SET", "arith", "v", "EX", "abc"), not_integer)
    check("SET EXAT non-numeric", conn.raw("SET", "arith", "v", "EXAT", "abc"), not_integer)
    check("GETEX EX non-numeric", conn.raw("GETEX", "arith", "EX", "abc"), not_integer)
    check("SETEX non-numeric", conn.raw("SETEX", "arith", "abc", "v"), not_integer)
    check("PSETEX non-numeric", conn.raw("PSETEX", "arith", "abc", "v"), not_integer)
    check("EXPIRE overflow stays invalid-expire",
          conn.raw("EXPIRE", "arith", "9223372036854775807"),
          b"-ERR invalid expire time in 'expire' command\r\n")
    check("SET EX overflow stays invalid-expire",
          conn.raw("SET", "arith", "v", "EX", "9223372036854775807"),
          b"-ERR invalid expire time in 'set' command\r\n")

    conn.cmd("SET", "arith", "v")
    check("PEXPIRE zero deletes", conn.cmd("PEXPIRE", "arith", "0"), 1)
    check("PEXPIRE zero effect", conn.cmd("EXISTS", "arith"), 0)
    conn.cmd("SET", "arith", "v")
    check("PEXPIRE INT64_MIN deletes", conn.cmd("PEXPIRE", "arith", "-9223372036854775808"), 1)
    conn.cmd("SET", "arith", "v")
    check("PEXPIREAT INT64_MAX accepted",
          conn.cmd("PEXPIREAT", "arith", "9223372036854775807"), 1)
    check("PEXPIREAT INT64_MAX exact", conn.cmd("PEXPIRETIME", "arith"), 9223372036854775807)
    check("first PERSIST", conn.cmd("PERSIST", "arith"), 1)
    check("TTL-free PERSIST control", conn.cmd("PERSIST", "arith"), 0)

    # GETEX shares SET's extended-argument grammar: one form may repeat (last value wins), two
    # different forms are a syntax error, and PERSIST may not be mixed with a deadline.
    conn.cmd("SET", "gx", "v")
    check("GETEX repeated EX", conn.cmd("GETEX", "gx", "EX", "10", "EX", "20"), b"v")
    check("GETEX repeated EX last wins", conn.cmd("TTL", "gx"), 20)
    check("GETEX repeated PERSIST", conn.cmd("GETEX", "gx", "PERSIST", "PERSIST"), b"v")
    check("GETEX repeated PERSIST cleared", conn.cmd("TTL", "gx"), -1)
    for options in (("EX", "10", "PX", "20000"), ("EX", "10", "PERSIST"), ("PERSIST", "EX", "10"),
                    ("FOO",), ("EX",)):
        check("GETEX syntax %s" % " ".join(options),
              conn.raw("GETEX", "gx", *options), b"-ERR syntax error\r\n")
    check("GETEX still TTL-free after refusals", conn.cmd("TTL", "gx"), -1)
    check("GETEX missing key beats bad deadline", conn.cmd("GETEX", "gx:absent", "EX", "abc"), None)

    conn.cmd("SET", "keep", "old", "PXAT", str(future_ms))
    conn.cmd("SET", "keep", "new", "KEEPTTL")
    check("SET KEEPTTL exact deadline", conn.cmd("PEXPIRETIME", "keep"), future_ms)
    check("GETEX past returns old value", conn.cmd("GETEX", "keep", "PXAT", "1"), b"new")
    check("GETEX past deletes", conn.cmd("GET", "keep"), None)


# --------------------------------------------------------------------------------------------
# Lazy versus active expiry, and the introspection surface.
# --------------------------------------------------------------------------------------------

def scan_all(conn):
    cursor = b"0"
    seen = set()
    rounds = 0
    while True:
        reply = conn.cmd("SCAN", cursor, "COUNT", "100")
        if not isinstance(reply, list) or len(reply) != 2:
            raise AssertionError("bad SCAN reply %r" % (reply,))
        cursor, keys = reply
        seen.update(keys)
        rounds += 1
        if cursor == b"0":
            return seen, rounds
        if rounds > 4000:
            raise AssertionError("SCAN did not terminate")


def seed_elapsed(conn, name):
    """One live key plus one key whose deadline has passed but which nothing has reaped yet."""
    conn.cmd("FLUSHALL")
    conn.cmd("SET", "lazy:live", "v")
    before = info_counter(conn, "expired_keys")
    conn.cmd("SET", "lazy:" + name, "v", "PX", "70")
    time.sleep(0.16)
    return before


def test_lazy_and_active(conn):
    set_active(conn, 0)

    before = seed_elapsed(conn, "dbsize")
    check("DBSIZE counts the expired-unreaped key", conn.cmd("DBSIZE"), 2)
    check("DBSIZE itself does not reap", info_counter(conn, "expired_keys") - before, 0)
    check("EXISTS hides it lazily", conn.cmd("EXISTS", "lazy:dbsize"), 0)
    check("DBSIZE case fired lazy expiry", info_counter(conn, "expired_keys") - before, 1)

    # MEMORY USAGE is deliberately the one form that answers from residency, matching redis's raw
    # dictionary read: the bytes are still held, so the size is still reported.
    lazy_cases = (
        ("keys", lambda: set(conn.cmd("KEYS", "*")), {b"lazy:live"}, 1),
        ("scan", lambda: scan_all(conn)[0], {b"lazy:live"}, 1),
        ("type", lambda: conn.cmd("TYPE", "lazy:type"), b"none", 1),
        ("object", lambda: conn.cmd("OBJECT", "ENCODING", "lazy:object"), None, 1),
        ("idletime", lambda: conn.cmd("OBJECT", "IDLETIME", "lazy:idletime"), None, 1),
        ("ttl", lambda: conn.cmd("TTL", "lazy:ttl"), -2, 1),
        ("persist", lambda: conn.cmd("PERSIST", "lazy:persist"), 0, 1),
        ("dump", lambda: conn.cmd("DUMP", "lazy:dump"), None, 1),
    )
    for name, action, want, fired in lazy_cases:
        before = seed_elapsed(conn, name)
        check("lazy %s reply" % name, action(), want)
        check("lazy %s mechanism fired" % name,
              info_counter(conn, "expired_keys") - before, fired)

    before = seed_elapsed(conn, "memory")
    usage = conn.cmd("MEMORY", "USAGE", "lazy:memory")
    check_true("MEMORY USAGE reports the resident expired key",
               isinstance(usage, int) and usage > 0, "got %r" % (usage,))
    check("MEMORY USAGE does not reap", info_counter(conn, "expired_keys") - before, 0)
    check("MEMORY USAGE nil once really gone", conn.cmd("MEMORY", "USAGE", "lazy:absent"), None)
    check("EXISTS still hides it", conn.cmd("EXISTS", "lazy:memory"), 0)
    check("lazy reap still available after MEMORY USAGE",
          info_counter(conn, "expired_keys") - before, 1)

    # Negative detector control: the same introspection over TTL-free keys must move no counter.
    conn.cmd("FLUSHALL")
    conn.cmd("SET", "lazy:control", "v")
    before = info_counter(conn, "expired_keys")
    check("TTL-free KEYS control", set(conn.cmd("KEYS", "*")), {b"lazy:control"})
    check("TTL-free SCAN control", scan_all(conn)[0], {b"lazy:control"})
    check("TTL-free RANDOMKEY control", conn.cmd("RANDOMKEY"), b"lazy:control")
    check("TTL-free TYPE control", conn.cmd("TYPE", "lazy:control"), b"string")
    check("TTL-free PERSIST control", conn.cmd("PERSIST", "lazy:control"), 0)
    check_true("TTL-free MEMORY USAGE control",
               isinstance(conn.cmd("MEMORY", "USAGE", "lazy:control"), int), "live key reported nil")
    check("lazy detector zero control", info_counter(conn, "expired_keys") - before, 0)

    # Active expiry must collect keys that no command ever touches.
    conn.cmd("FLUSHALL")
    set_active(conn, 1)
    before = info_counter(conn, "expired_keys")
    conn.cmd("SET", "active:live", "v")
    for index in range(128):
        conn.cmd("SET", "active:dead:%03d" % index, "v", "PX", "180")
    deadline = time.monotonic() + 5.0
    observed = None
    while time.monotonic() < deadline:
        observed = conn.cmd("DBSIZE")
        if observed == 1:
            break
        time.sleep(0.02)
    check("active expiry reached live-only DBSIZE", observed, 1)
    check("active expiry counter fired exactly 128",
          info_counter(conn, "expired_keys") - before, 128)

    conn.cmd("FLUSHALL")
    before = info_counter(conn, "expired_keys")
    for index in range(32):
        conn.cmd("SET", "active:control:%03d" % index, "v")
    time.sleep(0.25)
    check("active TTL-free DBSIZE control", conn.cmd("DBSIZE"), 32)
    check("active detector zero control", info_counter(conn, "expired_keys") - before, 0)


# --------------------------------------------------------------------------------------------
# MULTI / EXEC and WATCH.
# --------------------------------------------------------------------------------------------

def test_multi_watch(conn):
    other = Resp()
    try:
        set_active(conn, 0)
        conn.cmd("FLUSHALL")

        before = info_counter(conn, "expired_keys")
        conn.cmd("SET", "multi:queued", "v", "PX", "70")
        check("MULTI before queued expiry", conn.cmd("MULTI"), b"OK")
        check("GET queued before expiry", conn.cmd("GET", "multi:queued"), b"QUEUED")
        time.sleep(0.16)
        check("expired between queue and EXEC", conn.cmd("EXEC"), [None])
        check("queued expiry mechanism fired", info_counter(conn, "expired_keys") - before, 1)

        conn.cmd("SET", "multi:inside", "v")
        conn.cmd("MULTI")
        conn.cmd("PEXPIRE", "multi:inside", "0")
        conn.cmd("GET", "multi:inside")
        check("immediate expiry inside EXEC", conn.cmd("EXEC"), [1, None])

        # A key that was ALIVE when WATCH armed and whose deadline has since passed must abort
        # EXEC.  Active expiry is off, so the key is still physically counted: the abort has to
        # come from the armed deadline, not from a delete somebody else already performed.
        conn.cmd("FLUSHALL")
        before = info_counter(conn, "expired_keys")
        conn.cmd("SET", "watch:elapsed", "v", "PX", "70")
        check("WATCH elapsed setup", conn.cmd("WATCH", "watch:elapsed"), b"OK")
        time.sleep(0.16)
        check("WATCH key is still physically present", conn.cmd("DBSIZE"), 1)
        check("WATCH did not reap on arm", info_counter(conn, "expired_keys") - before, 0)
        conn.cmd("MULTI")
        conn.cmd("GET", "watch:elapsed")
        check("WATCH expiry aborts EXEC", conn.cmd("EXEC"), None)
        check("WATCH abort did not rely on a lazy reap",
              info_counter(conn, "expired_keys") - before, 0)
        check("post-abort EXISTS hides key", conn.cmd("EXISTS", "watch:elapsed"), 0)
        check("post-abort lazy detector fired", info_counter(conn, "expired_keys") - before, 1)

        # A key that was ALREADY past its deadline when WATCH armed is redis's `wk->expired`: its
        # later removal is not a change, so EXEC runs.  This is the control that keeps the row
        # above from passing for the trivial reason "every WATCH on a TTL key aborts".
        conn.cmd("FLUSHALL")
        conn.cmd("SET", "watch:prexp", "v", "PX", "60")
        time.sleep(0.15)
        check("pre-expired key still physically present", conn.cmd("DBSIZE"), 1)
        conn.cmd("WATCH", "watch:prexp")
        time.sleep(0.15)
        conn.cmd("MULTI")
        conn.cmd("GET", "watch:prexp")
        check("WATCH on already-elapsed key does NOT abort", conn.cmd("EXEC"), [None])

        conn.cmd("SET", "watch:future", "v", "PX", "10000")
        conn.cmd("WATCH", "watch:future")
        conn.cmd("MULTI")
        conn.cmd("GET", "watch:future")
        check("unelapsed WATCH negative control", conn.cmd("EXEC"), [b"v"])

        conn.cmd("SET", "watch:nottl", "v")
        conn.cmd("WATCH", "watch:nottl")
        conn.cmd("MULTI")
        conn.cmd("GET", "watch:nottl")
        check("TTL-free WATCH negative control", conn.cmd("EXEC"), [b"v"])

        conn.cmd("DEL", "watch:missing")
        conn.cmd("WATCH", "watch:missing")
        time.sleep(0.10)
        conn.cmd("MULTI")
        conn.cmd("GET", "watch:missing")
        check("unchanged missing WATCH control", conn.cmd("EXEC"), [None])

        conn.cmd("DEL", "watch:changed")
        conn.cmd("WATCH", "watch:changed")
        other.cmd("SET", "watch:changed", "v", "PX", "70")
        time.sleep(0.16)
        conn.cmd("MULTI")
        conn.cmd("GET", "watch:changed")
        check("missing key created then expired still aborts", conn.cmd("EXEC"), None)

        # Several watched keys spread over several owners: one elapsing is enough.
        conn.cmd("FLUSHALL")
        keys, _ = distinct_shard_keys(conn, "edgetime:watch", 4)
        for key in keys:
            conn.cmd("SET", key, "v")
        conn.cmd("PEXPIRE", keys[2], "80")
        conn.cmd("WATCH", *keys)
        time.sleep(0.20)
        conn.cmd("MULTI")
        conn.cmd("GET", keys[0])
        check("cross-shard WATCH aborts on one elapsed key", conn.cmd("EXEC"), None)

        for key in keys:
            conn.cmd("SET", key, "v")
        conn.cmd("WATCH", *keys)
        time.sleep(0.20)
        conn.cmd("MULTI")
        conn.cmd("GET", keys[0])
        check("cross-shard WATCH TTL-free control", conn.cmd("EXEC"), [b"v"])
    finally:
        set_active(conn, 1)
        other.close()


# --------------------------------------------------------------------------------------------
# Hash-field deadlines against whole-key deadlines.
# --------------------------------------------------------------------------------------------

def test_hash_whole_key(conn):
    conn.cmd("FLUSHALL")
    future = int(time.time() * 1000) + 3600000
    conn.cmd("HSET", "hwhole", "a", "1", "b", "2")
    check("field deadline setup",
          conn.cmd("HPEXPIREAT", "hwhole", str(future), "FIELDS", "1", "a"), [1])
    check("whole-key deadline setup", conn.cmd("PEXPIREAT", "hwhole", str(future + 5000)), 1)
    check("whole-key PERSIST", conn.cmd("PERSIST", "hwhole"), 1)
    check("PERSIST leaves the field deadline",
          conn.cmd("HPEXPIRETIME", "hwhole", "FIELDS", "2", "a", "b"), [future, -1])
    check("whole-key immediate expiry", conn.cmd("PEXPIREAT", "hwhole", "1"), 1)
    check("whole-key expiry dominates a live field", conn.cmd("EXISTS", "hwhole"), 0)

    conn.cmd("HSET", "hlast", "only", "v")
    check("last field immediate expiry",
          conn.cmd("HPEXPIREAT", "hlast", "1", "FIELDS", "1", "only"), [2])
    check("last field expiry removes the hash", conn.cmd("EXISTS", "hlast"), 0)

    conn.cmd("DEL", "hmix")
    conn.cmd("HSET", "hmix", "x", "1", "y", "2")
    conn.cmd("HPEXPIREAT", "hmix", "1", "FIELDS", "1", "x")
    check("elapsed field hidden from HGET", conn.cmd("HGET", "hmix", "x"), None)
    check("elapsed field gone from HLEN", conn.cmd("HLEN", "hmix"), 1)
    check("elapsed field deadline reads -2",
          conn.cmd("HPEXPIRETIME", "hmix", "FIELDS", "2", "x", "y"), [-2, -1])
    check("HPERSIST on an elapsed field", conn.cmd("HPERSIST", "hmix", "FIELDS", "1", "x"), [-2])
    check("rewriting the field clears its deadline", conn.cmd("HINCRBY", "hmix", "x", "5"), 5)
    check("rewritten field is TTL-free",
          conn.cmd("HPEXPIRETIME", "hmix", "FIELDS", "1", "x"), [-1])


# --------------------------------------------------------------------------------------------
# Expiry meeting the cross-shard commands.
# --------------------------------------------------------------------------------------------

def distinct_shard_keys(conn, prefix, count=8):
    by_shard = {}
    for index in range(4000):
        key = "%s:%04d" % (prefix, index)
        shard = conn.cmd("DEBUG", "SHARD", key)
        if isinstance(shard, int) and shard not in by_shard:
            by_shard[shard] = key
        if len(by_shard) == count:
            break
    if len(by_shard) != count:
        raise AssertionError("DEBUG SHARD found only %d distinct shards" % len(by_shard))
    return list(by_shard.values()), sorted(by_shard)


def test_multikey_ttl(conn):
    set_active(conn, 0)
    conn.cmd("FLUSHALL")
    keys, shards = distinct_shard_keys(conn, "edgetime:multi")
    check_true("multi-key geometry really spans eight shards", len(shards) == 8,
               "shards=%r" % shards)

    before = info_counter(conn, "expired_keys")
    for key in keys:
        conn.cmd("SET", key, "v", "PX", "70")
    time.sleep(0.16)
    check("cross-shard MGET hides every elapsed key", conn.cmd("MGET", *keys), [None] * len(keys))
    check("cross-shard MGET fired lazy expiry on every key",
          info_counter(conn, "expired_keys") - before, len(keys))

    before = info_counter(conn, "expired_keys")
    for key in keys:
        conn.cmd("SET", key, "v", "PX", "70")
    time.sleep(0.16)
    check("cross-shard DEL does not count elapsed keys", conn.cmd("DEL", *keys), 0)
    check("cross-shard DEL fired lazy expiry on every key",
          info_counter(conn, "expired_keys") - before, len(keys))

    before = info_counter(conn, "expired_keys")
    for key in keys:
        conn.cmd("SET", key, "v")
    check("TTL-free cross-shard DEL control", conn.cmd("DEL", *keys), len(keys))
    check("cross-shard expiry detector zero control",
          info_counter(conn, "expired_keys") - before, 0)

    future = int(time.time() * 1000) + 3600000
    source, destination = keys[0], keys[1]
    conn.cmd("SET", source, "payload")
    conn.cmd("PEXPIREAT", source, str(future))
    conn.cmd("DEL", destination)
    check("cross-shard RENAME of a TTL-bearing source", conn.cmd("RENAME", source, destination),
          b"OK")
    check("cross-shard RENAME carries the absolute deadline",
          conn.cmd("PEXPIRETIME", destination), future)

    conn.cmd("SET", source, "payload", "PX", "70")
    time.sleep(0.16)
    check("RENAME of an elapsed source is no-such-key",
          conn.cmd("RENAME", source, destination), RespError("ERR no such key"))

    set_a, set_b, store_destination = keys[2:5]
    conn.cmd("SADD", set_a, "x", "y")
    conn.cmd("SADD", set_b, "x", "z")
    conn.cmd("SET", store_destination, "old", "PXAT", str(future))
    check("cross-shard SINTERSTORE result",
          conn.cmd("SINTERSTORE", store_destination, set_a, set_b), 1)
    check("SINTERSTORE clears the old destination deadline",
          conn.cmd("PTTL", store_destination), -1)
    check("SINTERSTORE materialised the intersection",
          conn.cmd("SMEMBERS", store_destination), [b"x"])

    conn.cmd("PEXPIRE", set_b, "0")
    check("SINTERSTORE with an expired source is empty",
          conn.cmd("SINTERSTORE", store_destination, set_a, set_b), 0)
    check("empty SINTERSTORE removes the destination", conn.cmd("EXISTS", store_destination), 0)

    # OBJECT and MEMORY name their key in argv[2].  The program-order seam paired op.hash (the
    # real key) with op.key() (the literal "ENCODING"/"USAGE"), so no record matched and a younger
    # container subcommand ran past an older cross-shard group of its OWN connection.  The commit
    # delay is the tree's own window widener: without it the race is real but only lands ~1 time in
    # 10, which is not a verdict.  GET names its key in argv[1] and is the control that must never
    # tear, with or without the widener.
    probe_key, probe_a, probe_b = keys[5:8]
    rounds = 24
    check("commit-delay hook armed", conn.cmd("DEBUG", "ATOMIC-COMMIT-DELAY", "2000"), b"OK")
    missing = {"OBJECT ENCODING": 0, "MEMORY USAGE": 0, "GET": 0}
    stale = {"OBJECT ENCODING": 0, "MEMORY USAGE": 0, "GET": 0}
    for _ in range(rounds):
        conn.cmd("DEL", probe_key, probe_a, probe_b)
        created = conn.pipeline((
            ("MSET", probe_key, "created", probe_a, "a", probe_b, "b"),
            ("OBJECT", "ENCODING", probe_key),
            ("MEMORY", "USAGE", probe_key),
            ("GET", probe_key),
        ))
        if created[1] is None:
            missing["OBJECT ENCODING"] += 1
        if not isinstance(created[2], int):
            missing["MEMORY USAGE"] += 1
        if created[3] != b"created":
            missing["GET"] += 1
        conn.cmd("MSET", probe_key, "v", probe_a, "v", probe_b, "v")
        removed = conn.pipeline((
            ("DEL", probe_key, probe_a, probe_b),
            ("OBJECT", "ENCODING", probe_key),
            ("MEMORY", "USAGE", probe_key),
            ("GET", probe_key),
        ))
        if removed[1] is not None:
            stale["OBJECT ENCODING"] += 1
        if removed[2] is not None:
            stale["MEMORY USAGE"] += 1
        if removed[3] is not None:
            stale["GET"] += 1
    check("commit-delay hook disarmed", conn.cmd("DEBUG", "ATOMIC-COMMIT-DELAY", "0"), b"OK")
    for name in ("OBJECT ENCODING", "GET"):
        check("%s never misses its own cross-shard creation (%d rounds)" % (name, rounds),
              missing[name], 0)
        check("%s never resurrects its own cross-shard DEL (%d rounds)" % (name, rounds),
              stale[name], 0)
    check("MEMORY USAGE never misses its own cross-shard creation (%d rounds)" % rounds,
          missing["MEMORY USAGE"], 0)
    check("MEMORY USAGE never resurrects its own cross-shard DEL (%d rounds)" % rounds,
          stale["MEMORY USAGE"], 0)

    conn.cmd("SET", probe_key, "live")
    check_true("OBJECT ENCODING present control",
               conn.cmd("OBJECT", "ENCODING", probe_key) is not None, "live key reported nil")
    set_active(conn, 1)


# --------------------------------------------------------------------------------------------
# SHELVED-defect reproducer (not part of `all`).
# --------------------------------------------------------------------------------------------

def repro_hop_expiry(conn):
    """Cross-shard fan-out has no pinned TIME cut, only a pinned commit cut.

    Widen the fan-out with the tree's own DEBUG hook and give every key one shared deadline inside
    that window: the lead fragment answers from before the deadline and the parked fragments answer
    from after it, so one MGET reports a keyspace that never existed.  The control runs the SAME
    widened fan-out over keys whose deadline is an hour away and must show no tear at all.
    """
    conn.cmd("FLUSHALL")
    set_active(conn, 0)
    keys, shards = distinct_shard_keys(conn, "edgetime:hop")
    defer_us = 500000

    def trial(offset_ms):
        for key in keys:
            conn.cmd("SET", key, "v")
        deadline = int(time.time() * 1000) + offset_ms
        for key in keys:
            conn.cmd("PEXPIREAT", key, str(deadline))
        if conn.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", str(defer_us)) != b"OK":
            raise AssertionError("fan-out defer hook rejected")
        start = time.monotonic()
        reply = conn.cmd("MGET", *keys)
        elapsed = time.monotonic() - start
        conn.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", "0")
        return sum(value is not None for value in reply), elapsed, reply

    control_present, control_elapsed, _ = trial(3600000)
    armed_present, armed_elapsed, armed_reply = trial(defer_us // 2000)
    natural = 0
    for _ in range(200):
        for key in keys:
            conn.cmd("SET", key, "v")
        deadline = int(time.time() * 1000)
        for key in keys:
            conn.cmd("PEXPIREAT", key, str(deadline))
        reply = conn.cmd("MGET", *keys)
        present = sum(value is not None for value in reply)
        if 0 < present < len(keys):
            natural += 1
    set_active(conn, 1)

    print("geometry: 8 distinct shards %s" % shards)
    print("control (fan-out widened %dus, deadline 1h out): present=%d/8 elapsed=%.3fs"
          % (defer_us, control_present, control_elapsed))
    print("armed   (fan-out widened %dus, deadline inside): present=%d/8 elapsed=%.3fs reply=%r"
          % (defer_us, armed_present, armed_elapsed, armed_reply))
    print("natural (no hook, deadline == now): torn %d/200" % natural)
    if control_present != len(keys):
        print("EDGETIME HOP EXPIRY: CONTROL TORE -- the widened fan-out alone is not innocent")
        return 1
    if 0 < armed_present < len(keys) and armed_elapsed >= defer_us / 2.0e6:
        print("EDGETIME HOP EXPIRY: REPRODUCED (shelved cross-shard fan-out time-cut defect)")
        return 1
    print("EDGETIME HOP EXPIRY: NOT REPRODUCED")
    return 0


def repro_randomkey(conn):
    """RANDOMKEY answers nil while the keyspace is not empty, once expiry inflates a shard count.

    The IO thread picks ONE owner for RANDOMKEY and prefers an owner whose PUBLISHED key count is
    nonzero.  That count includes keys that are past their deadline but not yet reaped, so an owner
    that holds nothing but elapsed keys still looks populated; its `random_live()` sweep then reaps
    them and reports nothing, and the answer is nil even though live keys sit on other owners.
    Redis has one keyspace and retries until it finds a live key, so it never answers nil here.

    The control is the same shape without deadlines: TTL-free keys spread over the same owners must
    give a nil rate of zero, which is what makes the armed rate mean something.
    """
    rounds = 200
    armed_nil = 0
    control_nil = 0
    for _ in range(rounds):
        conn.cmd("FLUSHALL")
        conn.cmd("SET", "randomkey:live", "v")
        for index in range(40):
            conn.cmd("SET", "randomkey:dead:%03d" % index, "v", "PX", "30")
        time.sleep(0.045)
        if conn.cmd("RANDOMKEY") is None:
            armed_nil += 1
    for _ in range(rounds):
        conn.cmd("FLUSHALL")
        conn.cmd("SET", "randomkey:live", "v")
        for index in range(40):
            conn.cmd("SET", "randomkey:ctl:%03d" % index, "v")
        time.sleep(0.045)
        if conn.cmd("RANDOMKEY") is None:
            control_nil += 1
    print("control (40 TTL-free companions): nil %d/%d" % (control_nil, rounds))
    print("armed   (40 elapsed companions) : nil %d/%d" % (armed_nil, rounds))
    if control_nil:
        print("EDGETIME RANDOMKEY: CONTROL RETURNED NIL -- the detector proves nothing")
        return 1
    if armed_nil:
        print("EDGETIME RANDOMKEY: REPRODUCED (shelved shard-choice/expiry defect)")
        return 1
    print("EDGETIME RANDOMKEY: NOT REPRODUCED")
    return 0


# --------------------------------------------------------------------------------------------
# Persistence halves, driven by tests/edgetime_persist.sh.
# --------------------------------------------------------------------------------------------

def persist_build(conn):
    conn.cmd("FLUSHALL")
    if conn.cmd("DEBUG", "SET-ACTIVE-EXPIRE", "0") != b"OK":
        raise AssertionError("DEBUG SET-ACTIVE-EXPIRE 0 rejected")
    future = int(time.time() * 1000) + 3600000
    conn.cmd("SET", "persist:future", "future-value")
    conn.cmd("PEXPIREAT", "persist:future", str(future))
    conn.cmd("SET", "persist:elapsed", "must-not-return", "PX", "2000")
    conn.cmd("HSET", "persist:hash", "a", "1", "b", "2")
    conn.cmd("HPEXPIREAT", "persist:hash", str(future), "FIELDS", "1", "a")
    conn.cmd("PEXPIREAT", "persist:hash", str(future + 5000))
    conn.cmd("PERSIST", "persist:hash")
    # Long enough that replaying the original RELATIVE PX would resurrect the key for two seconds,
    # while the post-restart check still has a wide detector window.
    time.sleep(2.20)
    if conn.cmd("DBSIZE") != 3:
        raise AssertionError("elapsed key was not left physically unreaped before persistence")
    print("PERSIST_DEADLINE=%d" % future)
    print("edgetime persist build: PASS")
    return 0


def persist_check(conn, future):
    checks = (
        ("future value", conn.cmd("GET", "persist:future"), b"future-value"),
        ("future deadline", conn.cmd("PEXPIRETIME", "persist:future"), future),
        ("elapsed key absent", conn.cmd("GET", "persist:elapsed"), None),
        ("hash values", conn.cmd("HMGET", "persist:hash", "a", "b"), [b"1", b"2"]),
        ("field deadline", conn.cmd("HPEXPIRETIME", "persist:hash", "FIELDS", "2", "a", "b"),
         [future, -1]),
        ("whole hash stayed TTL-free", conn.cmd("PTTL", "persist:hash"), -1),
    )
    failed = [(name, got, want) for name, got, want in checks if got != want]
    for name, got, want in failed:
        print("  FAIL %s: got %r want %r" % (name, got, want))
    print("edgetime persist: %d checks, %d failures -> %s" %
          (len(checks), len(failed), "PASS" if not failed else "FAIL"))
    return 1 if failed else 0


def main():
    conn = Resp()
    try:
        if MODE == "repro-hop":
            return repro_hop_expiry(conn)
        if MODE == "repro-randomkey":
            return repro_randomkey(conn)
        if MODE == "persistbuild":
            return persist_build(conn)
        if MODE.startswith("persistcheck:"):
            return persist_check(conn, int(MODE.split(":", 1)[1]))
        if MODE != "all":
            raise SystemExit("unknown mode %s" % MODE)
        test_expire_options(conn)
        test_lazy_and_active(conn)
        test_multi_watch(conn)
        test_hash_whole_key(conn)
        test_multikey_ttl(conn)
    finally:
        if MODE != "persistbuild":
            try:
                conn.cmd("DEBUG", "ATOMIC-FANOUT-DEFER", "0")
                conn.cmd("DEBUG", "SET-ACTIVE-EXPIRE", "1")
            except Exception:
                pass
        conn.close()

    for failure in FAILURES:
        print("  FAIL " + failure)
    print("edgetime: %d checks, %d failures -> %s" %
          (CHECKS, len(FAILURES), "PASS" if not FAILURES else "FAIL"))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
