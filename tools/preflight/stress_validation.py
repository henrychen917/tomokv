#!/usr/bin/env python3
"""
stress_validation.py -- workload engine for tools/preflight/stress_validation.sh

ONE long-lived server per phase. This process runs for the WHOLE phase so that
long-lived connections opened at t=0 are still open at t=end: "no connection drops
after a certain run time" is only testable if nothing reconnects behind our back.

WHAT THIS IS FOR, and why it is shaped like this
------------------------------------------------
A soak, not a functional suite. correctness_suite.sh already answers "does command X
work once". This answers the questions that only appear over TIME and under
CONCURRENCY:

  * does memory come back when the keyspace shrinks (leak / QSBR reclaim stall)
  * does throughput hold after hours and hundreds of millions of commands
  * do results stay correct while buckets are being resharded and io/ex threads
    are being flipped underneath the traffic
  * do connections survive, and does connect/disconnect churn leak anything

DESIGN RULES LEARNED THE HARD WAY (do not "simplify" these away)
---------------------------------------------------------------
1. EVERY measurement is like-for-like. Memory is compared at the SAME key count,
   quiesced, after reclaim has been given a chance to run. Raw "memory went up
   while we added keys" is not a leak and must never be reported as one.
2. QSBR reclaim runs ON WORKER PASSES. After a shrink the workers must be given
   traffic, or retired memory is simply not reclaimed yet and a clean server looks
   like a leaking one. Hence drain_traffic() before every memory sample.
3. Throughput calibration runs EXCLUSIVE -- all lanes pause. A number measured
   while other lanes compete is not comparable to one measured when they did not.
4. ENGAGEMENT IS ASSERTED. A green run where no flip happened, no bucket moved and
   no table resized has tested nothing. Those are hard FAILs, not warnings.
   (This project has shipped machinery whose gate never opened.)
5. Oracles must DISCRIMINATE. --selftest injects faults and requires them caught.
6. -LOADING is a valid, expected reply (DEBUG RELOAD). Any client that cannot
   retry through it is broken -- that is a real finding about memtier, not the
   server. Every lane here retries.
"""

import argparse, json, os, random, re, socket, subprocess, sys, threading, time
from collections import defaultdict

# ------------------------------------------------------------------ RESP client

class RespError(Exception):
    def __init__(self, msg):
        super().__init__(msg)
        self.msg = msg

def transient(msg):
    """Replies that mean "not now, ask again", NOT "your request was wrong".

    LOADING: the DEBUG RELOAD window.
    BUSY <space>: TomoKV serialises scripts ("one script at a time in phase 1"), so concurrent
      EVAL lanes legitimately collide. Upstream's "BUSY Redis is busy running a script" is the
      same shape. The trailing space matters -- BUSYKEY (RESTORE onto an existing key) and
      BUSYGROUP (consumer group exists) are real errors and must NOT be retried away.

    A client that cannot retry through these is broken; treating them as failures is how a
    harness invents defects that are not there."""
    return msg.startswith("LOADING") or msg.startswith("BUSY ")

class Conn:
    """Minimal RESP2 client. Deliberately not redis-py: this needs exact control of
    pipelining and of reply-count-vs-request-count, because a LOST REPLY must show
    up as a read timeout rather than being silently absorbed."""

    def __init__(self, host, port, timeout=30.0, name=""):
        self.host, self.port, self.timeout, self.name = host, port, timeout, name
        self.sock = self.f = None
        self.opened_at = time.time()
        self.connect()

    def connect(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.sock.settimeout(self.timeout)
        self.f = self.sock.makefile("rwb")

    def close(self, reset=False):
        try:
            if reset and self.sock:
                # abortive close (RST) -- exercises the server's abrupt-disconnect path
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                                     b"\x01\x00\x00\x00\x00\x00\x00\x00")
        except Exception:
            pass
        for h in (self.f, self.sock):
            try:
                if h: h.close()
            except Exception:
                pass
        self.f = self.sock = None

    @staticmethod
    def _enc(args):
        out = bytearray(b"*%d\r\n" % len(args))
        for a in args:
            if isinstance(a, str):   a = a.encode()
            elif isinstance(a, int): a = str(a).encode()
            elif isinstance(a, float): a = repr(a).encode()
            out += b"$%d\r\n" % len(a); out += a; out += b"\r\n"
        return bytes(out)

    def _read(self, in_array=False):
        line = self.f.readline()
        if not line:
            raise ConnectionError("EOF from server")
        t, body = line[:1], line[1:-2]
        if t == b"+": return body.decode()
        if t == b":": return int(body)
        if t == b"-":
            e = RespError(body.decode())
            if in_array: return e          # keep stream in sync inside arrays
            raise e
        if t == b"$":
            n = int(body)
            if n == -1: return None
            data = self.f.read(n + 2)
            if data is None or len(data) < n + 2:
                raise ConnectionError("short bulk read")
            return data[:-2]
        if t == b"*":
            n = int(body)
            if n == -1: return None
            return [self._read(in_array=True) for _ in range(n)]
        raise ConnectionError("bad RESP type %r (line=%r)" % (t, line[:64]))

    def cmd(self, *args, retry_loading=True):
        """One command, one reply. Retries through -LOADING (DEBUG RELOAD window)."""
        deadline = time.time() + 60
        while True:
            self.f.write(self._enc(args)); self.f.flush()
            try:
                return self._read()
            except RespError as e:
                if retry_loading and transient(e.msg) and time.time() < deadline:
                    time.sleep(0.02); continue
                raise

    def pipe(self, cmds, retry_loading=True):
        """Send N, read exactly N.

        A dropped reply surfaces here as a socket timeout -- but so does a lane whose Python thread
        was simply not scheduled for `timeout` seconds, and this process runs a thread per lane
        while parsing tens of millions of replies. Those two are indistinguishable from in here, so
        the timeout is NOT the verdict: Engine.fail() takes a fresh-connection control before any
        timeout is allowed to accuse the server. That control is not optional -- without it this
        harness reported a DEBUG RELOAD reply-loss defect that did not exist (docs/BUGS.md M)."""
        deadline = time.time() + 60
        while True:
            buf = bytearray()
            for c in cmds: buf += self._enc(c)
            self.f.write(bytes(buf)); self.f.flush()
            out, loading = [], False
            for _ in cmds:
                try:
                    out.append(self._read())
                except RespError as e:
                    if transient(e.msg): loading = True
                    out.append(e)
            if loading and retry_loading and time.time() < deadline:
                time.sleep(0.05); continue
            return out

# ------------------------------------------------------------------ assertions

class OracleFail(Exception):
    pass

def eq(got, want, what):
    if isinstance(want, bytes) and isinstance(got, bytes):
        ok = got == want
    elif isinstance(want, (list, tuple)):
        ok = list(got or []) == list(want)
    else:
        ok = got == want
    if not ok:
        raise OracleFail("%s: got %r want %r" % (what, got, want))

def s(v):
    return v.decode() if isinstance(v, bytes) else v

def bset(v):
    return set(x if isinstance(x, bytes) else str(x).encode() for x in (v or []))

# ------------------------------------------------------------------ scenarios
# Each scenario is self-contained: it owns its keys, asserts exact results, and
# cleans up. They run continuously, interleaved, while flips/reshards/resizes
# happen underneath. `ns` is unique per invocation so concurrent copies of the
# same scenario never collide.

def sc_strings(c, ns):
    k = f"{ns}:s"
    eq(c.cmd("SET", k, "hello"), "OK", "SET")
    eq(c.cmd("GET", k), b"hello", "GET")
    eq(c.cmd("APPEND", k, "-world"), 11, "APPEND len")
    eq(c.cmd("GET", k), b"hello-world", "GET after APPEND")
    eq(c.cmd("STRLEN", k), 11, "STRLEN")
    eq(c.cmd("GETRANGE", k, 0, 4), b"hello", "GETRANGE")
    eq(c.cmd("GETRANGE", k, -5, -1), b"world", "GETRANGE neg")
    eq(c.cmd("SETRANGE", k, 0, "HELLO"), 11, "SETRANGE")
    eq(c.cmd("GET", k), b"HELLO-world", "GET after SETRANGE")
    eq(c.cmd("SETNX", k, "nope"), 0, "SETNX existing")
    eq(c.cmd("GETDEL", k), b"HELLO-world", "GETDEL")
    eq(c.cmd("EXISTS", k), 0, "EXISTS after GETDEL")
    eq(c.cmd("SET", k, "v", "EX", 100), "OK", "SET EX")
    ttl = c.cmd("TTL", k)
    if not (90 <= ttl <= 100): raise OracleFail("SET EX ttl=%r" % ttl)
    eq(c.cmd("PERSIST", k), 1, "PERSIST")
    eq(c.cmd("TTL", k), -1, "TTL after PERSIST")
    c.cmd("DEL", k)

def sc_numeric(c, ns):
    k = f"{ns}:n"
    c.cmd("DEL", k)
    eq(c.cmd("INCR", k), 1, "INCR")
    eq(c.cmd("INCRBY", k, 41), 42, "INCRBY")
    eq(c.cmd("DECRBY", k, 2), 40, "DECRBY")
    eq(c.cmd("DECR", k), 39, "DECR")
    v = s(c.cmd("INCRBYFLOAT", k, "0.5"))
    if float(v) != 39.5: raise OracleFail("INCRBYFLOAT=%r" % v)
    c.cmd("SET", k, "notanumber")
    try:
        c.cmd("INCR", k); raise OracleFail("INCR on non-numeric should error")
    except RespError as e:
        if "not an integer" not in e.msg: raise OracleFail("INCR err=%s" % e.msg)
    c.cmd("DEL", k)

def sc_mset_mget(c, ns):
    # multi-key: on a sharded server these fan out across workers (cross-shard path)
    keys = [f"{ns}:m{i}" for i in range(12)]
    pairs = []
    for i, k in enumerate(keys): pairs += [k, f"val{i}"]
    eq(c.cmd("MSET", *pairs), "OK", "MSET")
    got = c.cmd("MGET", *keys)
    eq(got, [f"val{i}".encode() for i in range(12)], "MGET")
    # MGET with a hole must return nil in the right POSITION -- position mapping is
    # exactly what the cross-shard gather has to get right.
    c.cmd("DEL", keys[5])
    got = c.cmd("MGET", *keys)
    if got[5] is not None: raise OracleFail("MGET hole not nil: %r" % got[5])
    eq(got[6], b"val6", "MGET after hole")
    eq(c.cmd("MSETNX", keys[5], "x", keys[0], "y"), 0, "MSETNX with existing")
    eq(c.cmd("EXISTS", keys[5]), 0, "MSETNX must be all-or-nothing")
    c.cmd("DEL", *keys)

def sc_lists(c, ns):
    k = f"{ns}:l"
    c.cmd("DEL", k)
    eq(c.cmd("RPUSH", k, "a", "b", "c"), 3, "RPUSH")
    eq(c.cmd("LPUSH", k, "z"), 4, "LPUSH")
    eq(c.cmd("LRANGE", k, 0, -1), [b"z", b"a", b"b", b"c"], "LRANGE")
    eq(c.cmd("LLEN", k), 4, "LLEN")
    eq(c.cmd("LINDEX", k, 1), b"a", "LINDEX")
    eq(c.cmd("LPOP", k), b"z", "LPOP")
    eq(c.cmd("RPOP", k), b"c", "RPOP")
    eq(c.cmd("LSET", k, 0, "A"), "OK", "LSET")
    eq(c.cmd("LINSERT", k, "BEFORE", "b", "mid"), 3, "LINSERT")
    eq(c.cmd("LRANGE", k, 0, -1), [b"A", b"mid", b"b"], "LRANGE after insert")
    eq(c.cmd("LREM", k, 1, "mid"), 1, "LREM")
    eq(c.cmd("LTRIM", k, 0, 0), "OK", "LTRIM")
    eq(c.cmd("LRANGE", k, 0, -1), [b"A"], "LRANGE after trim")
    r = c.cmd("LMPOP", 1, k, "LEFT")
    if r is None or s(r[0]) != k: raise OracleFail("LMPOP=%r" % r)
    c.cmd("DEL", k)

def sc_hashes(c, ns):
    k = f"{ns}:h"
    c.cmd("DEL", k)
    eq(c.cmd("HSET", k, "f1", "v1", "f2", "v2"), 2, "HSET")
    eq(c.cmd("HGET", k, "f1"), b"v1", "HGET")
    eq(c.cmd("HLEN", k), 2, "HLEN")
    eq(c.cmd("HEXISTS", k, "f2"), 1, "HEXISTS")
    eq(c.cmd("HMGET", k, "f1", "f2", "nope"), [b"v1", b"v2", None], "HMGET")
    eq(c.cmd("HSETNX", k, "f1", "other"), 0, "HSETNX existing")
    eq(c.cmd("HINCRBY", k, "cnt", 5), 5, "HINCRBY")
    eq(bset(c.cmd("HKEYS", k)), {b"f1", b"f2", b"cnt"}, "HKEYS")
    eq(bset(c.cmd("HVALS", k)), {b"v1", b"v2", b"5"}, "HVALS")
    ga = c.cmd("HGETALL", k)
    d = {s(ga[i]): ga[i+1] for i in range(0, len(ga), 2)}
    eq(d.get("f1"), b"v1", "HGETALL f1")
    eq(c.cmd("HDEL", k, "f1"), 1, "HDEL")
    # HSCAN must return every field of a key nobody else is touching
    seen, cur = set(), 0
    while True:
        cur, batch = c.cmd("HSCAN", k, cur)
        cur = int(s(cur))
        for i in range(0, len(batch), 2): seen.add(s(batch[i]))
        if cur == 0: break
    eq(seen, {"f2", "cnt"}, "HSCAN completeness")
    c.cmd("DEL", k)

def sc_sets(c, ns):
    k = f"{ns}:set"
    c.cmd("DEL", k)
    eq(c.cmd("SADD", k, "a", "b", "c"), 3, "SADD")
    eq(c.cmd("SCARD", k), 3, "SCARD")
    eq(c.cmd("SISMEMBER", k, "b"), 1, "SISMEMBER")
    eq(c.cmd("SMISMEMBER", k, "a", "zzz"), [1, 0], "SMISMEMBER")
    eq(bset(c.cmd("SMEMBERS", k)), {b"a", b"b", b"c"}, "SMEMBERS")
    eq(c.cmd("SREM", k, "a"), 1, "SREM")
    seen, cur = set(), 0
    while True:
        cur, batch = c.cmd("SSCAN", k, cur)
        cur = int(s(cur)); seen |= bset(batch)
        if cur == 0: break
    eq(seen, {b"b", b"c"}, "SSCAN completeness")
    c.cmd("DEL", k)

def sc_setops(c, ns):
    # cross-shard set ops -- this is the pipeline that leaked position-map rows (J1)
    a, b, d = f"{ns}:sa", f"{ns}:sb", f"{ns}:sd"
    c.cmd("DEL", a, b, d)
    c.cmd("SADD", a, *[f"m{i}" for i in range(20)])
    c.cmd("SADD", b, *[f"m{i}" for i in range(10, 30)])
    eq(bset(c.cmd("SINTER", a, b)), {f"m{i}".encode() for i in range(10, 20)}, "SINTER")
    eq(c.cmd("SINTERCARD", 2, a, b), 10, "SINTERCARD")
    eq(c.cmd("SINTERCARD", 2, a, b, "LIMIT", 3), 3, "SINTERCARD LIMIT")
    eq(len(c.cmd("SUNION", a, b)), 30, "SUNION")
    eq(bset(c.cmd("SDIFF", a, b)), {f"m{i}".encode() for i in range(10)}, "SDIFF")
    eq(c.cmd("SINTERSTORE", d, a, b), 10, "SINTERSTORE")
    eq(c.cmd("SCARD", d), 10, "SINTERSTORE result")
    # empty-input short circuit
    eq(c.cmd("SINTER", a, f"{ns}:missing"), [], "SINTER with missing key")
    c.cmd("DEL", a, b, d)

def sc_zsets(c, ns):
    k = f"{ns}:z"
    c.cmd("DEL", k)
    eq(c.cmd("ZADD", k, 1, "one", 2, "two", 3, "three"), 3, "ZADD")
    eq(c.cmd("ZCARD", k), 3, "ZCARD")
    eq(s(c.cmd("ZSCORE", k, "two")), "2", "ZSCORE")
    eq(c.cmd("ZRANGE", k, 0, -1), [b"one", b"two", b"three"], "ZRANGE")
    eq(c.cmd("ZRANGE", k, 0, -1, "REV"), [b"three", b"two", b"one"], "ZRANGE REV")
    eq(c.cmd("ZRANK", k, "two"), 1, "ZRANK")
    eq(c.cmd("ZCOUNT", k, 2, 3), 2, "ZCOUNT")
    eq(s(c.cmd("ZINCRBY", k, 5, "one")), "6", "ZINCRBY")
    eq(c.cmd("ZRANGEBYSCORE", k, 2, 3), [b"two", b"three"], "ZRANGEBYSCORE")
    r = c.cmd("ZPOPMIN", k)
    eq(s(r[0]), "two", "ZPOPMIN")
    eq(c.cmd("ZREM", k, "three"), 1, "ZREM")
    eq(c.cmd("ZRANGE", k, 0, -1), [b"one"], "ZRANGE final")
    c.cmd("DEL", k)

def sc_zsetops(c, ns):
    a, b = f"{ns}:za", f"{ns}:zb"
    c.cmd("DEL", a, b)
    c.cmd("ZADD", a, 1, "x", 2, "y")
    c.cmd("ZADD", b, 3, "y", 4, "z")
    eq(c.cmd("ZUNION", 2, a, b), [b"x", b"z", b"y"], "ZUNION order")
    eq(c.cmd("ZINTER", 2, a, b), [b"y"], "ZINTER")
    eq(c.cmd("ZDIFF", 2, a, b), [b"x"], "ZDIFF")
    eq(c.cmd("ZINTERCARD", 2, a, b), 1, "ZINTERCARD")
    c.cmd("DEL", a, b)

def sc_bitmap(c, ns):
    k = f"{ns}:bit"
    c.cmd("DEL", k)
    eq(c.cmd("SETBIT", k, 7, 1), 0, "SETBIT")
    eq(c.cmd("GETBIT", k, 7), 1, "GETBIT")
    eq(c.cmd("BITCOUNT", k), 1, "BITCOUNT")
    eq(c.cmd("BITPOS", k, 1), 7, "BITPOS")
    c.cmd("SET", f"{ns}:b1", "abc"); c.cmd("SET", f"{ns}:b2", "abd")
    c.cmd("BITOP", "AND", f"{ns}:bdst", f"{ns}:b1", f"{ns}:b2")
    if c.cmd("GET", f"{ns}:bdst") is None: raise OracleFail("BITOP produced nothing")
    r = c.cmd("BITFIELD", k, "SET", "u8", 0, 255, "GET", "u8", 0)
    eq(r[1], 255, "BITFIELD GET")
    c.cmd("DEL", k, f"{ns}:b1", f"{ns}:b2", f"{ns}:bdst")

def sc_hll(c, ns):
    k, k2, d = f"{ns}:hll", f"{ns}:hll2", f"{ns}:hlld"
    c.cmd("DEL", k, k2, d)
    c.cmd("PFADD", k, *[f"e{i}" for i in range(100)])
    n = c.cmd("PFCOUNT", k)
    if not (80 <= n <= 120): raise OracleFail("PFCOUNT=%r out of band" % n)
    c.cmd("PFADD", k2, *[f"e{i}" for i in range(50, 150)])
    c.cmd("PFMERGE", d, k, k2)
    m = c.cmd("PFCOUNT", d)
    if not (120 <= m <= 180): raise OracleFail("PFMERGE count=%r" % m)
    c.cmd("DEL", k, k2, d)

def sc_streams(c, ns):
    k = f"{ns}:st"
    c.cmd("DEL", k)
    i1 = s(c.cmd("XADD", k, "*", "f", "1"))
    s(c.cmd("XADD", k, "*", "f", "2"))
    eq(c.cmd("XLEN", k), 2, "XLEN")
    rng = c.cmd("XRANGE", k, "-", "+")
    eq(len(rng), 2, "XRANGE len")
    eq(s(rng[0][0]), i1, "XRANGE first id")
    eq(len(c.cmd("XREVRANGE", k, "+", "-")), 2, "XREVRANGE")
    eq(c.cmd("XDEL", k, i1), 1, "XDEL")
    eq(c.cmd("XLEN", k), 1, "XLEN after XDEL")
    c.cmd("DEL", k)

def sc_expiry(c, ns):
    k = f"{ns}:e"
    eq(c.cmd("SETEX", k, 100, "v"), "OK", "SETEX")
    t = c.cmd("TTL", k)
    if not (90 <= t <= 100): raise OracleFail("SETEX TTL=%r" % t)
    eq(c.cmd("EXPIRE", k, 200), 1, "EXPIRE")
    if c.cmd("EXPIRETIME", k) <= int(time.time()): raise OracleFail("EXPIRETIME in past")
    eq(c.cmd("GETEX", k, "PERSIST"), b"v", "GETEX PERSIST")
    eq(c.cmd("TTL", k), -1, "TTL after GETEX PERSIST")
    eq(c.cmd("PEXPIRE", k, 100000), 1, "PEXPIRE")
    if c.cmd("PTTL", k) <= 0: raise OracleFail("PTTL not positive")
    c.cmd("DEL", k)
    eq(c.cmd("TTL", k), -2, "TTL of missing key")
    # a key that really does expire, verified by observation not by trust
    c.cmd("SET", f"{ns}:gone", "v", "PX", 60)
    time.sleep(0.25)
    eq(c.cmd("GET", f"{ns}:gone"), None, "expired key must read as nil")
    eq(c.cmd("EXISTS", f"{ns}:gone"), 0, "expired key must not EXIST")

def sc_keyspace(c, ns):
    a, b = f"{ns}:k1", f"{ns}:k2"
    c.cmd("DEL", a, b)
    c.cmd("SET", a, "v")
    eq(s(c.cmd("TYPE", a)), "string", "TYPE")
    eq(c.cmd("COPY", a, b), 1, "COPY")
    eq(c.cmd("GET", b), b"v", "COPY value")
    eq(c.cmd("COPY", a, b), 0, "COPY without REPLACE must refuse")
    eq(c.cmd("COPY", a, b, "REPLACE"), 1, "COPY REPLACE")
    r = f"{ns}:k3"; c.cmd("DEL", r)
    eq(c.cmd("RENAME", b, r), "OK", "RENAME")
    eq(c.cmd("EXISTS", b), 0, "RENAME removes source")
    eq(c.cmd("RENAMENX", r, a), 0, "RENAMENX onto existing")
    eq(c.cmd("UNLINK", a, r), 2, "UNLINK")
    eq(c.cmd("EXISTS", a, r), 0, "EXISTS after UNLINK")

def sc_dump_restore(c, ns):
    a, b = f"{ns}:d1", f"{ns}:d2"
    c.cmd("DEL", a, b)
    c.cmd("RPUSH", a, "x", "y", "z")
    payload = c.cmd("DUMP", a)
    if payload is None: raise OracleFail("DUMP returned nil")
    eq(c.cmd("RESTORE", b, 0, payload), "OK", "RESTORE")
    eq(c.cmd("LRANGE", b, 0, -1), [b"x", b"y", b"z"], "RESTORE fidelity")
    c.cmd("DEL", a, b)

def sc_scan(c, ns):
    """SCAN guarantees: a key present for the WHOLE iteration is returned. Our own namespace is
    untouched by other lanes, so exact completeness is assertable -- and this runs while the flat
    table is being REBUILT and buckets are being resharded underneath the cursor, which is the
    interesting part.

    Two things this got wrong the first time, both worth keeping in mind:
      * MATCH filters the OUTPUT, it does not shorten the WALK. A full iteration costs
        dbsize/COUNT round trips no matter how narrow the pattern, so COUNT must be large or the
        scenario alone dominates the lane (it did: 45 scenario executions in a phase instead of
        930, and six later scenarios never ran at all).
      * the termination guard has to scale with the KEYSPACE, not be a constant. A fixed 20000
        was fine at 150k keys and tripped at ~500k, reporting a harness limit as a server defect.
    """
    keys = [f"{ns}:sc{i}" for i in range(40)]
    c.cmd("MSET", *[x for k in keys for x in (k, "v")])
    try:
        dbsize = int(s(c.cmd("DBSIZE")))
    except Exception:
        dbsize = 1000000
    count = 1000
    # 10x the round trips a perfectly even walk would need, with a floor: SCAN may revisit
    # buckets across a rehash/resize, so some slack is legitimate, but an unbounded loop is not.
    guard_max = max(2000, (dbsize // count + 1) * 10)
    seen, cur, guard = set(), 0, 0
    while True:
        cur, batch = c.cmd("SCAN", cur, "MATCH", f"{ns}:sc*", "COUNT", count)
        cur = int(s(cur)); seen |= bset(batch)
        guard += 1
        if cur == 0: break
        if guard > guard_max:
            raise OracleFail(f"SCAN did not terminate in {guard} iterations "
                             f"(dbsize={dbsize} count={count} guard_max={guard_max})")
    missing = bset(keys) - seen
    if missing:
        raise OracleFail("SCAN missed %d of its own keys e.g. %r (dbsize=%d)"
                         % (len(missing), sorted(missing)[:3], dbsize))
    c.cmd("DEL", *keys)

def sc_txn_guard(c, ns):
    """MULTI/EXEC/WATCH are REFUSED under sharding, by design: a transaction would execute
    against the empty decoy db and its writes would be silently lost. The thing that must be
    true forever is that the guard FIRES -- a regression here is silent data loss, so this
    asserts the rejection rather than the feature."""
    for verb in ("MULTI", "WATCH", "EXEC", "DISCARD"):
        args = (verb, f"{ns}:w") if verb == "WATCH" else (verb,)
        try:
            r = c.cmd(*args)
            raise OracleFail(f"{verb} must be refused under sharding, got {r!r}")
        except RespError as e:
            if "not supported with tomokv sharding" not in e.msg and "without MULTI" not in e.msg:
                raise OracleFail(f"{verb} rejected with the wrong error: {e.msg}")

def sc_script(c, ns):
    """EVAL is argc-gated under sharding: the keyless form runs, the KEYED form is refused
    (it would span shards and hit the decoy db). Both halves are asserted -- if the keyless
    form ever started being refused, or the keyed form ever started silently succeeding,
    that is the regression."""
    eq(c.cmd("EVAL", "return 1", 0), 1, "EVAL keyless int")
    eq(c.cmd("EVAL", "return 'ok'", 0), b"ok", "EVAL keyless string")
    try:
        r = c.cmd("EVAL", "return redis.call('GET', KEYS[1])", 1, f"{ns}:lua")
        raise OracleFail(f"keyed EVAL must be refused under sharding, got {r!r}")
    except RespError as e:
        if "not yet supported with tomokv sharding" not in e.msg:
            raise OracleFail(f"keyed EVAL rejected with the wrong error: {e.msg}")

def sc_pipeline_order(c, ns):
    """Same-client pipelined ordering is a hard invariant here (the cs_barrier defect
    class). Interleave single-key and MULTI-KEY commands on ONE connection: the
    multi-key ones take the scatter/gather path, and reordering against neighbours
    would corrupt this sequence."""
    k, m1, m2 = f"{ns}:po", f"{ns}:po_a", f"{ns}:po_b"
    c.cmd("DEL", k, m1, m2)
    cmds, want = [], []
    for i in range(60):
        cmds.append(("SET", k, str(i)));          want.append("OK")
        cmds.append(("GET", k));                  want.append(str(i).encode())
        cmds.append(("MSET", m1, str(i), m2, str(i))); want.append("OK")
        cmds.append(("MGET", k, m1, m2))
        want.append([str(i).encode()] * 3)
    got = c.pipe(cmds)
    for i, (g, w) in enumerate(zip(got, want)):
        if isinstance(g, RespError): raise OracleFail("pipeline err at %d: %s" % (i, g.msg))
        eq(g, w, "pipeline order idx %d (%s)" % (i, cmds[i][0]))
    c.cmd("DEL", k, m1, m2)

def sc_type_errors(c, ns):
    k = f"{ns}:te"
    c.cmd("DEL", k); c.cmd("RPUSH", k, "x")
    for args in (("GET", k), ("INCR", k), ("SADD", k, "y"), ("HGET", k, "f")):
        try:
            c.cmd(*args); raise OracleFail("%s on list should WRONGTYPE" % args[0])
        except RespError as e:
            if "WRONGTYPE" not in e.msg: raise OracleFail("%s err=%s" % (args[0], e.msg))
    c.cmd("DEL", k)

def sc_object_encoding(c, ns):
    """Regression guard for J7: OBJECT/MEMORY USAGE carry their key at argv[2], so before the
    fix they were never dispatched, ran inline against the empty decoy db, and answered nil for
    keys that plainly existed. A nil here means that routing has broken again."""
    k = f"{ns}:oe"
    c.cmd("DEL", k); c.cmd("RPUSH", k, "a")
    enc = s(c.cmd("OBJECT", "ENCODING", k))
    if not enc: raise OracleFail("OBJECT ENCODING nil -- decoy-db routing regression (J7)")
    if c.cmd("OBJECT", "REFCOUNT", k) is None:
        raise OracleFail("OBJECT REFCOUNT nil -- decoy-db routing regression (J7)")
    mu = c.cmd("MEMORY", "USAGE", k)
    if mu in (None, 0): raise OracleFail("MEMORY USAGE nil/0 -- decoy-db routing regression (J7)")
    c.cmd("DEL", k)
    if c.cmd("OBJECT", "ENCODING", k) is not None:
        # after DEL the key is gone; upstream errors, and we must at least not report a value
        raise OracleFail("OBJECT ENCODING returned a value for a deleted key")

SCENARIOS = [
    ("strings", sc_strings), ("numeric", sc_numeric), ("mset_mget", sc_mset_mget),
    ("lists", sc_lists), ("hashes", sc_hashes), ("sets", sc_sets),
    ("setops", sc_setops), ("zsets", sc_zsets), ("zsetops", sc_zsetops),
    ("bitmap", sc_bitmap), ("hll", sc_hll), ("streams", sc_streams),
    ("expiry", sc_expiry), ("keyspace", sc_keyspace), ("dump_restore", sc_dump_restore),
    ("scan", sc_scan), ("txn_guard", sc_txn_guard), ("script", sc_script),
    ("pipeline_order", sc_pipeline_order), ("type_errors", sc_type_errors),
    ("object_encoding", sc_object_encoding),
]

# ------------------------------------------------------------------ the engine

class Engine:
    def __init__(self, a):
        self.a = a
        self.stop = threading.Event()
        self.pause = threading.Event()      # set => ALL lanes idle (exclusive calibration)
        # DEBUG RELOAD is save -> FLUSH -> load, so every key written after the snapshot is
        # legitimately discarded. A lane that asserts its own writes survive cannot also run
        # across a reload -- the two requirements contradict. Value-asserting lanes stand down
        # for the reload; bulk/skew/churn keep hammering, so the reload still happens under
        # real concurrent load (which is what found J3 and exercised the J4 watchdog).
        self.oracle_pause = threading.Event()
        self.lock = threading.Lock()
        self.failures = []                  # hard failures; first one ends the run
        self.ops = defaultdict(int)
        self.scenario_runs = defaultdict(int)
        self.churn_ok = 0
        self.churn_fail = 0
        self.longlived = []
        self.metrics = []                   # per-cycle samples
        self.threads = []
        self.parked_lanes = 0   # lanes currently parked in wait_while_paused (see await_quiet)

    # -- helpers ---------------------------------------------------------------
    def conn(self, name=""):
        return Conn(self.a.host, self.a.port, timeout=self.a.timeout, name=name)

    def server_is_serving(self, budget=3.0):
        """Is the SERVER serving right now, on a connection that has no history?

        This is the control that a timeout needs before it is allowed to accuse the server. Every
        lane here is a Python thread doing blocking reads while the process parses tens of millions
        of replies, so the threads contend for the GIL, and a lane that is simply not SCHEDULED for
        `timeout` seconds raises exactly the same socket timeout as a lane the server never
        answered. Those two are indistinguishable from inside the lane and need completely
        different responses.

        Measured 2026-08-02: a reducer built on the same thread-per-lane shape "reproduced" reply
        loss 3 runs of 3, and a rewrite of the SAME test around a single select() loop showed
        54,650,112 replies with 0 owed across DEBUG RELOAD. The defect was the apparatus. See
        docs/BUGS.md section M."""
        try:
            c = Conn(self.a.host, self.a.port, timeout=budget, name="control")
            try:
                return c.cmd("PING") == "PONG"
            finally:
                c.close()
        except Exception:
            return False

    def fail(self, where, detail):
        # A bare client-side timeout is NOT evidence of a server fault. Take the control first: if
        # a fresh connection is served promptly at this moment, the server was serving and this
        # lane was starved -- count it and let the run continue rather than burning the soak and
        # sending the next reader into the server for a client bug.
        if "TimeoutError" in detail or "timed out" in detail:
            if self.server_is_serving():
                with self.lock:
                    self.ops["client_stalls"] += 1
                    n = self.ops["client_stalls"]
                if n <= 5 or n % 50 == 0:
                    print(f"  [client-stall #{n}] [{where}] {detail} -- server answered a fresh "
                          f"PING immediately, so this is local scheduling, not the server",
                          flush=True)
                # A LOT of these means the driver cannot keep up and the soak is no longer
                # measuring the server; that is itself a failure, just a different one.
                if n <= self.a.max_client_stalls:
                    return
                detail = (f"{detail} -- and {n} client-side stalls exceeded the "
                          f"--max-client-stalls budget, so this driver can no longer be trusted "
                          f"to observe the server")

        ts = time.strftime("%H:%M:%S") + ".%03d" % int((time.time() % 1) * 1000)
        with self.lock:
            if not self.failures:
                print(f"\n!!! FAIL [{ts}] [{where}] {detail}", flush=True)
            self.failures.append((ts, where, detail))
        self.stop.set()

    def bump(self, k, n=1):
        with self.lock: self.ops[k] += n

    def info(self, c, section="everything"):
        raw = c.cmd("INFO", section)
        out = {}
        for line in s(raw).splitlines():
            if ":" in line and not line.startswith("#"):
                k, _, v = line.partition(":")
                out[k.strip()] = v.strip()
        return out

    def wait_while_paused(self, oracle=False):
        """Park here while paused, and ACKNOWLEDGE the park so calibrate() can know it is alone.

        Design rule 3 says calibration runs exclusive. It used to approximate that with a fixed
        1.5 s sleep after setting the flag, which is not the same thing: a bulk lane sitting inside
        one c.pipe() of thousands of commands does not look at the flag until that batch completes,
        so memtier started while lanes were still saturating the load cores. Measured 2026-08-02 —
        cycle 1 (200k keys) calibrated fine at 4.03M ops/s, cycle 2 (400k keys) had memtier starved
        until it blew its 140 s timeout and returned nothing, which the harness then correctly
        refused to treat as a measurement. Counting parked lanes turns "probably quiet by now" into
        a fact we can wait on."""
        parked = False
        try:
            while (self.pause.is_set() or (oracle and self.oracle_pause.is_set())) \
                    and not self.stop.is_set():
                if not parked:
                    parked = True
                    with self.lock:
                        self.parked_lanes += 1
                time.sleep(0.05)
        finally:
            if parked:
                with self.lock:
                    self.parked_lanes -= 1

    def await_quiet(self, budget=30.0):
        """Block until every lane thread is parked, or the budget expires.

        Returns (quiet, parked, expected). A calibration taken while lanes are still running is not
        comparable to one taken when they were not, so the caller must report a non-quiet window
        rather than silently publishing an incomparable number."""
        expected = len(self.threads)
        end = time.time() + budget
        while time.time() < end and not self.stop.is_set():
            with self.lock:
                parked = self.parked_lanes
            if parked >= expected:
                return True, parked, expected
            time.sleep(0.05)
        with self.lock:
            parked = self.parked_lanes
        return False, parked, expected

    # -- lanes -----------------------------------------------------------------
    def lane_scenarios(self, idx):
        """Interleaves EVERY command family, continuously, under load."""
        c = self.conn(f"scen{idx}")
        i = 0
        try:
            while not self.stop.is_set():
                self.wait_while_paused(oracle=True)
                if self.stop.is_set(): break
                name, fn = SCENARIOS[i % len(SCENARIOS)]
                ns = f"sv:sc{idx}:{i % 32}"
                try:
                    fn(c, ns)
                    with self.lock: self.scenario_runs[name] += 1
                    self.bump("scenario_ops")
                except OracleFail as e:
                    self.fail(f"oracle:{name}", str(e)); return
                except RespError as e:
                    self.fail(f"error-reply:{name}", e.msg); return
                except (ConnectionError, socket.timeout, OSError) as e:
                    self.fail(f"conn:{name}", f"{type(e).__name__}: {e}"); return
                i += 1
        except Exception as e:
            self.fail(f"lane_scenarios{idx}", f"{type(e).__name__}: {e}")
        finally:
            c.close()

    def lane_bulk(self, idx):
        """Sustained pipelined throughput -- keeps dispatch and the reply path hot."""
        c = self.conn(f"bulk{idx}")
        val = "v" * self.a.value_bytes
        n = 0
        try:
            while not self.stop.is_set():
                self.wait_while_paused()
                if self.stop.is_set(): break
                batch = []
                for _ in range(64):
                    k = f"sv:bulk:{random.randrange(self.a.bulk_keys)}"
                    batch.append(("SET", k, val) if random.random() < 0.3 else ("GET", k))
                out = c.pipe(batch)
                for r in out:
                    if isinstance(r, RespError):
                        self.fail("bulk", r.msg); return
                n += len(batch); self.bump("bulk_ops", len(batch))
        except (ConnectionError, socket.timeout, OSError) as e:
            self.fail("bulk-conn", f"{type(e).__name__}: {e} after {n} ops")
        except Exception as e:
            self.fail("bulk", f"{type(e).__name__}: {e}")
        finally:
            c.close()

    def lane_bigvals(self, idx):
        """Large values: exercises the reply/spill path (16K-64K) that once wedged."""
        c = self.conn(f"big{idx}")
        try:
            while not self.stop.is_set():
                self.wait_while_paused(oracle=True)
                if self.stop.is_set(): break
                size = random.choice([4096, 16384, 65536])
                k = f"sv:big:{random.randrange(256)}"
                payload = "x" * size
                c.cmd("SET", k, payload)
                got = c.cmd("GET", k)
                if got is None or len(got) != size:
                    self.fail("bigvals", f"GET {k} len={None if got is None else len(got)} want {size}"); return
                self.bump("bigval_ops", 2)
        except (ConnectionError, socket.timeout, OSError) as e:
            self.fail("bigvals-conn", f"{type(e).__name__}: {e}")
        except Exception as e:
            self.fail("bigvals", f"{type(e).__name__}: {e}")
        finally:
            c.close()

    def lane_churn(self, idx):
        """Connect/disconnect during high throughput, including abortive (RST) closes
        and closes with a command still in flight."""
        try:
            while not self.stop.is_set():
                self.wait_while_paused()
                if self.stop.is_set(): break
                mode = random.random()
                try:
                    c = self.conn(f"churn{idx}")
                    if mode < 0.4:
                        c.cmd("PING"); c.cmd("SET", f"sv:churn:{idx}", "1"); c.close()
                    elif mode < 0.7:
                        # close with a request in flight, reply never read
                        c.f.write(Conn._enc(("GET", f"sv:churn:{idx}"))); c.f.flush()
                        c.close()
                    else:
                        c.close(reset=True)            # abortive
                    with self.lock: self.churn_ok += 1
                except Exception as e:
                    with self.lock: self.churn_fail += 1
                    if self.churn_fail > 50:
                        self.fail("churn", f"{self.churn_fail} connect failures, last {type(e).__name__}: {e}")
                        return
                time.sleep(self.a.churn_sleep)
        except Exception as e:
            self.fail("churn", f"{type(e).__name__}: {e}")

    def lane_skew(self, idx):
        """Hot key / hot bucket -- this is what the key balancer is supposed to notice
        and reshard away from."""
        c = self.conn(f"skew{idx}")
        try:
            while not self.stop.is_set():
                self.wait_while_paused()
                if self.stop.is_set(): break
                hot = f"sv:hot:{idx}:{int(time.time()) // 30}"
                out = c.pipe([("INCR", hot)] * 128)
                for r in out:
                    if isinstance(r, RespError): self.fail("skew", r.msg); return
                self.bump("skew_ops", 128)
        except (ConnectionError, socket.timeout, OSError) as e:
            self.fail("skew-conn", f"{type(e).__name__}: {e}")
        except Exception as e:
            self.fail("skew", f"{type(e).__name__}: {e}")
        finally:
            c.close()

    def lane_longlived(self):
        """Connections opened at t=0 that must still work at t=end. This is the whole
        'no connection drops after a certain run time' requirement."""
        for i in range(self.a.longlived):
            try:
                c = self.conn(f"ll{i}")
                c.cmd("SET", f"sv:ll:{i}", f"ll{i}")
                self.longlived.append(c)
            except Exception as e:
                self.fail("longlived-setup", f"{type(e).__name__}: {e}"); return
        while not self.stop.is_set():
            time.sleep(2.0)
            if self.oracle_pause.is_set(): continue   # its value can vanish across a reload
            for i, c in enumerate(self.longlived):
                try:
                    if s(c.cmd("GET", f"sv:ll:{i}")) != f"ll{i}":
                        self.fail("longlived", f"conn {i} wrong value"); return
                    self.bump("longlived_ops")
                except Exception as e:
                    age = time.time() - c.opened_at
                    self.fail("longlived-drop",
                              f"conn {i} died after {age:.0f}s: {type(e).__name__}: {e}")
                    return

    # -- keyspace shaping ------------------------------------------------------
    def grow(self, c, target):
        """Grow the keyspace: drives FLATSTORE growth + resize."""
        val = "g" * 64
        i, batch = 0, []
        while i < target and not self.stop.is_set():
            batch = [("SET", f"sv:grow:{j}", val) for j in range(i, min(i + 512, target))]
            out = c.pipe(batch)
            for r in out:
                if isinstance(r, RespError): self.fail("grow", r.msg); return
            i += len(batch); self.bump("grow_ops", len(batch))

    def shrink(self, c, target):
        """Delete back down: drives retire/QSBR reclaim and (eventually) shrink."""
        i = 0
        while i < target and not self.stop.is_set():
            batch = [("DEL", f"sv:grow:{j}") for j in range(i, min(i + 512, target))]
            out = c.pipe(batch)
            for r in out:
                if isinstance(r, RespError): self.fail("shrink", r.msg); return
            i += len(batch); self.bump("shrink_ops", len(batch))

    def drain_traffic(self, c, seconds):
        """CRITICAL for honest memory numbers: QSBR reclaim happens on WORKER PASSES.
        Without traffic after a shrink, retired memory is simply not reclaimed yet and
        a perfectly clean server reads as leaking."""
        end = time.time() + seconds
        while time.time() < end and not self.stop.is_set():
            c.pipe([("PING",)] * 32)
            c.pipe([("GET", f"sv:ll:{i}") for i in range(min(8, self.a.longlived))])
            time.sleep(0.02)

    # -- measurement -----------------------------------------------------------
    def calibrate(self, tag):
        """EXCLUSIVE throughput probe. Lanes are paused so the number is comparable
        across cycles -- that is the entire point."""
        self.pause.set()
        # WAIT for the lanes to actually park, do not assume it. A fixed sleep here let memtier
        # start while a bulk lane was still inside one multi-thousand-command pipe(), so it
        # competed for the load cores with the traffic it was supposed to replace.
        quiet, parked, expected = self.await_quiet(self.a.quiesce_budget)
        ops = 0.0
        why = ""
        try:
            cmd = ["taskset", "-c", self.a.load_cores, "memtier_benchmark",
                   "-s", self.a.host, "-p", str(self.a.port), "--hide-histogram",
                   "--test-time", str(self.a.calib_secs), "--ratio", "1:9",
                   "--key-maximum", "200000", "-d", "32", "--key-pattern", "R:R",
                   "-t", "4", "-c", "10", "--pipeline", "16", "--distinct-client-seed"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=self.a.calib_secs + 120)
            m = re.search(r"^\s*Totals\s+(\d+(?:\.\d+)?)", r.stdout, re.M)
            if m:
                ops = float(m.group(1))
            else:
                # Keep the evidence. "memtier returned no throughput" with nothing behind it sent
                # me looking at the server for a load-generator problem.
                why = (f"no Totals line; rc={r.returncode} "
                       f"stdout_tail={r.stdout.strip()[-300:]!r} stderr_tail={r.stderr.strip()[-300:]!r}")
        except Exception as e:
            why = f"{type(e).__name__}: {e}"
            print(f"  calibrate({tag}) failed: {e}", flush=True)
        finally:
            self.pause.clear()
        if not quiet:
            # Not comparable, and saying so is the point -- publishing it would corrupt the
            # cross-cycle throughput trend that this whole case exists to check.
            self.fail("calibrate",
                      f"{tag}: lanes did not quiesce within {self.a.quiesce_budget}s "
                      f"({parked}/{expected} parked), so this window is not exclusive and any "
                      f"number from it is incomparable. {why}")
            return 0.0
        if ops <= 0:
            self.fail("calibrate",
                      f"{tag}: memtier returned no throughput (0 is never a measurement). {why}")
        return ops

    def sample(self, c, cycle, phase_t0):
        inf = self.info(c)
        rss = 0
        try:
            with open(f"/proc/{self.a.server_pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"): rss = int(line.split()[1]) * 1024; break
        except Exception:
            pass
        return {
            "cycle": cycle,
            "t": round(time.time() - phase_t0, 1),
            "dbsize": int(s(c.cmd("DBSIZE"))),
            "used_memory": int(inf.get("used_memory", 0)),
            "rss": rss,
            "ex_queue_full": int(inf.get("tomokv_ex_queue_full", 0)),
            "handoff_missed": int(inf.get("tomokv_handoff_missed", 0)),
            "resize_watchdog": int(inf.get("tomokv_flat_resize_watchdog_aborts", 0)),
            "resize_state": int(inf.get("tomokv_flat_resize_state", 0)),
            "expired_keys": int(inf.get("expired_keys", 0)),
            "total_commands": int(inf.get("total_commands_processed", 0)),
            "connected_clients_thread": int(inf.get("connected_clients", 0)),
        }

    # -- driver ----------------------------------------------------------------
    def run(self):
        random.seed(self.a.seed)
        phase_t0 = time.time()
        ctl = self.conn("ctl")

        # long-lived first, so they are genuinely present for the whole phase
        t = threading.Thread(target=self.lane_longlived, daemon=True); t.start(); self.threads.append(t)
        for i in range(self.a.scenario_lanes):
            t = threading.Thread(target=self.lane_scenarios, args=(i,), daemon=True); t.start(); self.threads.append(t)
        for i in range(self.a.bulk_lanes):
            t = threading.Thread(target=self.lane_bulk, args=(i,), daemon=True); t.start(); self.threads.append(t)
        for i in range(self.a.churn_lanes):
            t = threading.Thread(target=self.lane_churn, args=(i,), daemon=True); t.start(); self.threads.append(t)
        t = threading.Thread(target=self.lane_bigvals, args=(0,), daemon=True); t.start(); self.threads.append(t)
        t = threading.Thread(target=self.lane_skew, args=(0,), daemon=True); t.start(); self.threads.append(t)

        baseline_calib = None
        for cycle in range(1, self.a.cycles + 1):
            if self.stop.is_set(): break
            cyc_end = phase_t0 + (self.a.phase_secs * cycle / self.a.cycles)
            print(f"\n=== cycle {cycle}/{self.a.cycles} (t+{time.time()-phase_t0:.0f}s) ===", flush=True)

            print("  grow ...", flush=True)
            self.grow(ctl, self.a.high_keys)
            if self.stop.is_set(): break

            # steady mixed load until the cycle's mid-point
            mid = time.time() + max(10, (cyc_end - time.time()) * 0.45)
            while time.time() < mid and not self.stop.is_set():
                time.sleep(1.0)

            # DEBUG RELOAD under live load, on some cycles: a big, real edge case.
            if self.a.reload and cycle % 2 == 0 and not self.stop.is_set():
                print("  DEBUG RELOAD under load ...", flush=True)
                self.oracle_pause.set()
                time.sleep(1.0)          # let in-flight assertions finish before the flush
                try:
                    eq(ctl.cmd("DEBUG", "RELOAD"), "OK", "DEBUG RELOAD")
                    self.bump("reloads")
                except Exception as e:
                    self.fail("debug-reload", f"{type(e).__name__}: {e}")
                finally:
                    time.sleep(1.0)      # and let the keyspace settle before they resume
                    self.oracle_pause.clear()

            if self.stop.is_set(): break
            print("  shrink ...", flush=True)
            self.shrink(ctl, self.a.high_keys)
            if self.stop.is_set(): break

            print("  drain (let QSBR reclaim run) ...", flush=True)
            self.drain_traffic(ctl, self.a.drain_secs)

            # quiesced, same logical state as every other cycle => comparable
            self.pause.set(); time.sleep(2.0)
            try:
                m = self.sample(ctl, cycle, phase_t0)
            finally:
                self.pause.clear()

            calib = self.calibrate(f"cycle{cycle}")
            m["calib_ops"] = calib
            if baseline_calib is None: baseline_calib = calib
            self.metrics.append(m)
            print(f"  sample: dbsize={m['dbsize']} used_memory={m['used_memory']/1e6:.1f}MB "
                  f"rss={m['rss']/1e6:.1f}MB calib={calib:.0f} ops/s "
                  f"qfull={m['ex_queue_full']} handoff_missed={m['handoff_missed']}", flush=True)

            # handoff_missed is a RATE signal, not a must-be-zero invariant. A producer has to
            # store its item BEFORE OR-ing its summary bit (advertising first would let a consumer
            # drain, clear the bit, and only then have the item land -- the real strand), so there
            # is an inherent store-to-advertise window in which a lane holds work with no bit set.
            # Healthy servers show a handful per hundreds of millions of ops, WITHOUT flips
            # (measured: static 5 and 2, auto 0 -- so it is not the flip controller). The driver
            # applies a per-million-op ceiling instead; a systematically broken publish site would
            # be orders of magnitude above it.
            pass
            while time.time() < cyc_end and not self.stop.is_set():
                time.sleep(0.5)

        self.stop.set()
        for t in self.threads: t.join(timeout=10)
        for c in self.longlived: c.close()

        out = {
            "failures": self.failures,
            "metrics": self.metrics,
            "ops": dict(self.ops),
            "scenario_runs": dict(self.scenario_runs),
            "churn_ok": self.churn_ok,
            "churn_fail": self.churn_fail,
            "elapsed": round(time.time() - phase_t0, 1),
        }
        try:
            ctl.close()
        except Exception:
            pass
        return out

# ------------------------------------------------------------------ selftest

def selftest(a):
    """Prove the oracles DISCRIMINATE. A suite that cannot fail is not evidence.
    Each case corrupts an expectation and requires the oracle to notice."""
    c = Conn(a.host, a.port, timeout=a.timeout)
    passed = failed = 0

    # 1. every scenario must run clean against a healthy server
    for name, fn in SCENARIOS:
        try:
            fn(c, f"sv:selftest:{name}")
            passed += 1
        except Exception as e:
            print(f"  SELFTEST scenario {name} FAILED on a healthy server: {type(e).__name__}: {e}")
            failed += 1

    # 2. injected faults must be CAUGHT
    def must_catch(label, fn):
        nonlocal passed, failed
        try:
            fn(); print(f"  SELFTEST {label}: NOT CAUGHT (oracle is vacuous)"); failed += 1
        except (OracleFail, RespError, AssertionError):
            passed += 1
    must_catch("eq-detects-wrong-value", lambda: eq(b"a", b"b", "x"))
    must_catch("eq-detects-wrong-list", lambda: eq([b"a"], [b"a", b"b"], "x"))
    def wrong_get():
        c.cmd("SET", "sv:selftest:inj", "real")
        eq(c.cmd("GET", "sv:selftest:inj"), b"WRONG", "injected")
    must_catch("scenario-detects-bad-read", wrong_get)
    def wrong_scan():
        keys = [f"sv:selftest:sc{i}" for i in range(10)]
        c.cmd("MSET", *[x for k in keys for x in (k, "v")])
        seen = bset(keys[:5])
        missing = bset(keys) - seen
        if missing: raise OracleFail("scan missed")
    must_catch("scan-oracle-detects-missing", wrong_scan)
    def bad_pipeline_order():
        got = [b"0", b"1", b"2"]; want = [b"0", b"2", b"1"]
        for i, (g, w) in enumerate(zip(got, want)): eq(g, w, "order %d" % i)
    must_catch("pipeline-order-detects-swap", bad_pipeline_order)
    must_catch("type-error-oracle", lambda: (_ for _ in ()).throw(OracleFail("x")))

    c.close()
    print(f"SELFTEST SUMMARY pass={passed} fail={failed}")
    return 0 if failed == 0 else 1

# ------------------------------------------------------------------ main

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, required=True)
    p.add_argument("--server-pid", type=int, default=0)
    p.add_argument("--phase-secs", type=int, default=3000)
    p.add_argument("--cycles", type=int, default=4)
    p.add_argument("--high-keys", type=int, default=300000)
    p.add_argument("--bulk-keys", type=int, default=200000)
    p.add_argument("--value-bytes", type=int, default=64)
    p.add_argument("--scenario-lanes", type=int, default=3)
    p.add_argument("--bulk-lanes", type=int, default=4)
    p.add_argument("--churn-lanes", type=int, default=2)
    p.add_argument("--longlived", type=int, default=8)
    p.add_argument("--churn-sleep", type=float, default=0.02)
    p.add_argument("--drain-secs", type=int, default=20)
    p.add_argument("--calib-secs", type=int, default=20)
    p.add_argument("--timeout", type=float, default=30.0)
    # How many client-side stalls (a lane timeout that a fresh-connection control immediately
    # disproves) may be tolerated before the driver itself is declared untrustworthy. Non-zero
    # because GIL scheduling genuinely does starve a lane occasionally under this much parsing;
    # bounded because a driver that stalls constantly is no longer observing the server at all.
    p.add_argument("--max-client-stalls", type=int, default=20)
    # How long calibrate() waits for every lane to park before it gives up on an exclusive window.
    # Generous: a bulk lane inside one large pipe() legitimately takes seconds to notice the flag.
    p.add_argument("--quiesce-budget", type=float, default=45.0)
    p.add_argument("--load-cores", default="8-15")
    p.add_argument("--seed", type=int, default=1234)
    p.add_argument("--reload", type=int, default=1)
    p.add_argument("--json", default="")
    p.add_argument("--selftest", action="store_true")
    a = p.parse_args()

    if a.selftest:
        return selftest(a)

    eng = Engine(a)
    out = eng.run()
    if a.json:
        with open(a.json, "w") as f: json.dump(out, f, indent=1)
    print("\n--- lane totals ---")
    for k, v in sorted(out["ops"].items()): print(f"  {k}: {v}")
    print(f"  churn_ok: {out['churn_ok']}  churn_fail: {out['churn_fail']}")
    print("--- scenario executions ---")
    for k, v in sorted(out["scenario_runs"].items()): print(f"  {k}: {v}")
    never = [n for n, _ in SCENARIOS if out["scenario_runs"].get(n, 0) == 0]
    if never:
        print(f"COVERAGE-GAP scenarios never executed: {never}")
    if out["failures"]:
        for w, d in out["failures"][:5]: print(f"FAILURE [{w}] {d}")
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())
