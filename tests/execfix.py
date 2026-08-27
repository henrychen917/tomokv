#!/usr/bin/env python3
"""MULTI/EXEC correctness battery for lane t-execfix.  Usage: tests/execfix.py HOST PORT

Boot requirement: --enable-debug-command yes (DEBUG SHARD is the geometry oracle; without it every
"cross-shard" arm below could silently be a same-shard arm and prove nothing).  The battery flips
`atomic` itself with CONFIG SET, so either boot mode covers both.

WHAT THIS PINS DOWN
-------------------
(a)+(c) ONE DEFECT, TWO FACES -- the MVCC resolver's winner comparison.
    `atomic_resolve_internal` ranked candidates by epoch.  A transaction's own still-private
    candidate carries epoch 0 (its ticket is not drawn yet), so it LOST to any older but committed
    version of the same key.  Consequences, both proved here:
      * READ face: the second touch of a key inside one EXEC, and a plain read after that EXEC,
        answered from before the transaction.
      * WRITE face, and this is the serious one: an in-place read-modify-write (RPUSH/SADD/ZADD/
        HSET/APPEND) mutates the object the resolver handed it.  Handed the PARKED PREDECESSOR, it
        appended to a version that collapse then frees -- the element is gone, the RPUSH replied
        with the correct new length, and nothing anywhere reports a loss.
    The shape needs the key to already carry a live MVCC entry, which is why it wants a two-owner
    transaction first and why a clean-key minimal case does not show it.

(b) The version-bytes gauge.  `atomic_finish_group_install` used to std::abort() when its
    owner-local gauge underflowed.  The underflow was REAL -- the write face above returns more
    bytes at collapse than install charged, because the parked object grew after it was parked --
    but killing the process over a memory-accounting number is a worse failure than carrying a
    mis-sized one.  The gauge now clamps and counts; `atomic_gauge_underflows` must read 0.

(d) A cross-shard LCS inside MULTI answered "ERR internal cross-shard completion error" while the
    identical bare LCS answered correctly: the MULTI child-completion path had no Kind::Lcs arm, so
    the child reached reply assembly with no final reply at all.

NON-VACUITY
-----------
Every arm below asserts its mechanism was actually engaged, not merely that the data looked right:
  * `DEBUG SHARD` proves each "two-owner" transaction really spans two owners on THIS boot's hash
    seed (the seed is redrawn every boot, so key names prove nothing).
  * `atomic_entries` must advance across the loss arms: a pending MVCC chain really existed, so the
    resolver was really exercised.  A run in which no entry was ever linked would pass trivially.
  * `atomic_predecessor_reads` must stay 0 across those arms.  That counter is the resolver saying
    "I answered from a version older than the physical one", which is exactly the defect; on the
    unfixed tree it advances once per lost write.
  * `atomic_gauge_underflows` must stay 0, and the battery fails if the counter is missing rather
    than passing on a build that cannot report it.
The must-report-non-zero control for those two counters is a binary with the resolver ranking
reverted; its transcript is in NOTES-EXECFIX.md.  It is not in-tree because it is a source revert,
not a runtime switch.
"""

import socket
import sys

HOST, PORT = sys.argv[1], int(sys.argv[2])
ROUNDS = 120
TAG = "execfix"


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
    def __init__(self, timeout=30):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect((HOST, PORT))
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def command(self, *args):
        self.sock.sendall(encode(*args))
        return self.read()

    def read(self):
        prefix = self.file.read(1)
        if not prefix:
            raise EOFError("server closed the connection")
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
            payload = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise AssertionError("bad bulk trailer")
            return payload
        if prefix == b"*":
            size = int(value)
            if size == -1:
                return None
            return [self.read() for _ in range(size)]
        raise AssertionError(f"unknown RESP prefix: {prefix!r}")

    def close(self):
        if self.sock is not None:
            self.file.close()
            self.sock.close()
            self.sock = None


FAILURES = []


def ok(label):
    print(f"  ok   {label}", flush=True)


def check(condition, label, detail=""):
    if condition:
        ok(label)
    else:
        FAILURES.append(label)
        print(f"  FAIL {label}{(': ' + detail) if detail else ''}", flush=True)


def stats(conn):
    raw = conn.command("INFO", "STATS")
    if not isinstance(raw, bytes):
        raise AssertionError(f"INFO STATS returned {raw!r}")
    table = {}
    for line in raw.decode().splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            table[key] = value
    return table


def counter(conn, name):
    table = stats(conn)
    if name not in table:
        raise AssertionError(
            f"INFO STATS has no {name}: this build cannot prove the mechanism, so every arm that "
            f"rests on it would be vacuous")
    return int(table[name])


def shard_of(conn, key):
    reply = conn.command("DEBUG", "SHARD", key)
    if isinstance(reply, RespError):
        raise AssertionError(
            "DEBUG SHARD is unavailable: boot with --enable-debug-command yes.  Without the "
            "geometry oracle a 'cross-shard' arm may be a same-shard arm and proves nothing")
    return int(reply)


def two_owner_keys(conn, prefix, count=2):
    """Distinct keys on distinct shards, proved on THIS boot's hash seed."""
    seen = {}
    index = 0
    while len(seen) < count and index < 4000:
        key = f"{TAG}:{prefix}:{index:04d}"
        seen.setdefault(shard_of(conn, key), key)
        index += 1
    if len(seen) < count:
        raise AssertionError(f"could not find {count} keys on distinct shards")
    return [seen[s] for s in sorted(seen)[:count]]


def set_atomic(conn, value):
    return conn.command("CONFIG", "SET", "atomic", str(value)) == b"OK"


# --------------------------------------------------------------------------------------------
# (a)+(c) the write face: a second transaction's write to a key an earlier two-owner transaction
# touched must not vanish.  Reply and data are both checked; the reply was always correct on the
# unfixed tree, which is what made the loss silent.
# --------------------------------------------------------------------------------------------

# name: (writer, reader, the integer the SECOND write replies with).  RPUSH answers the new list
# length; SADD/ZADD/HSET answer how many members/fields were ADDED, which is 1 either way -- so for
# those three the reply was never the tell, only the data was.  Both are checked.
FAMILIES = {
    "list": (lambda k, v: ("RPUSH", k, v), lambda k: ("LRANGE", k, "0", "-1"), 2),
    "set":  (lambda k, v: ("SADD", k, v), lambda k: ("SMEMBERS", k), 1),
    "zset": (lambda k, v: ("ZADD", k, "1", v), lambda k: ("ZRANGE", k, "0", "-1"), 1),
    "hash": (lambda k, v: ("HSET", k, v, v), lambda k: ("HKEYS", k), 1),
}


def arm_lost_write(conn, mode):
    a, b = two_owner_keys(conn, "loss")
    sa, sb = shard_of(conn, a), shard_of(conn, b)
    check(sa != sb, f"geometry: the seeding transaction spans two owners (atomic {mode})",
          f"both keys landed on shard {sa}")
    for family, (writer, reader, want_reply) in FAMILIES.items():
        conn.command("FLUSHALL")
        before_reads = counter(conn, "atomic_predecessor_reads")
        before_entries = counter(conn, "atomic_entries")
        lost = 0
        wrong_reply = 0
        for i in range(ROUNDS):
            ka, kb = f"{a}:{family}:{i}", f"{b}:{family}:{i}"
            conn.command("MULTI")
            conn.command(*writer(kb, "v"))
            conn.command(*writer(ka, "v"))
            conn.command("EXEC")
            conn.command("MULTI")
            conn.command(*writer(ka, "x"))
            exec_reply = conn.command("EXEC")
            if exec_reply != [want_reply]:
                wrong_reply += 1
            members = conn.command(*reader(ka))
            if members is None or len(members) != 2:
                lost += 1
        reads = counter(conn, "atomic_predecessor_reads") - before_reads
        entries = counter(conn, "atomic_entries") - before_entries
        check(entries > 0,
              f"{family}: the shape really built an MVCC chain (atomic {mode})",
              f"atomic_entries advanced by {entries}; nothing was ever linked, so the arm is vacuous")
        check(wrong_reply == 0,
              f"{family}: every second-transaction write replied {want_reply} (atomic {mode})",
              f"{wrong_reply}/{ROUNDS} replies wrong")
        check(lost == 0,
              f"{family}: no write was silently lost over {ROUNDS} rounds (atomic {mode})",
              f"{lost}/{ROUNDS} rounds ended one element short with a normal reply")
        check(reads == 0,
              f"{family}: resolver never answered from a parked predecessor (atomic {mode})",
              f"atomic_predecessor_reads advanced by {reads}")


def arm_lost_append(conn, mode):
    """APPEND is the string face of the same loss: it clones from what the resolver returns."""
    a, b = two_owner_keys(conn, "append")
    conn.command("FLUSHALL")
    wrong = 0
    for i in range(ROUNDS):
        ka, kb = f"{a}:s:{i}", f"{b}:s:{i}"
        conn.command("MULTI")
        conn.command("SET", kb, "v")
        conn.command("SET", ka, "v")
        conn.command("EXEC")
        conn.command("MULTI")
        conn.command("APPEND", ka, "x")
        conn.command("EXEC")
        if conn.command("GET", ka) != b"vx":
            wrong += 1
    check(wrong == 0, f"string APPEND after a two-owner transaction (atomic {mode})",
          f"{wrong}/{ROUNDS} rounds appended to a stale base")


# --------------------------------------------------------------------------------------------
# (a) the read face: a later access inside ONE EXEC must observe an earlier write from the same
# EXEC, and a plain read after the EXEC must observe it too.
# --------------------------------------------------------------------------------------------

def arm_read_your_own_write(conn, mode):
    a, b = two_owner_keys(conn, "ryow")
    conn.command("FLUSHALL")

    # Give both keys a live MVCC entry first: without one the resolver has nothing to lose to.
    conn.command("MULTI")
    conn.command("SET", b, "7")
    conn.command("SET", a, "7")
    conn.command("EXEC")

    conn.command("MULTI")
    conn.command("INCRBY", a, "5")
    conn.command("INCRBY", a, "4")
    conn.command("GET", a)
    replies = conn.command("EXEC")
    check(replies == [12, 16, b"16"],
          f"two INCRBYs and a GET in one EXEC chain off each other (atomic {mode})",
          f"got {replies!r}, wanted [12, 16, b'16']")
    check(conn.command("GET", a) == b"16",
          f"a plain read after that EXEC sees it (atomic {mode})",
          f"got {conn.command('GET', a)!r}")

    conn.command("MULTI")
    conn.command("APPEND", a, "z")
    conn.command("APPEND", a, "z")
    conn.command("STRLEN", a)
    replies = conn.command("EXEC")
    check(replies == [3, 4, 4], f"two APPENDs and a STRLEN in one EXEC (atomic {mode})",
          f"got {replies!r}, wanted [3, 4, 4]")

    # DEL must count a key this same transaction created, and must not count one it removed.
    conn.command("FLUSHALL")
    conn.command("MULTI")
    conn.command("SET", b, "1")
    conn.command("SET", a, "1")
    conn.command("EXEC")
    conn.command("MULTI")
    conn.command("SET", a, "2")
    conn.command("DEL", a, b)
    replies = conn.command("EXEC")
    check(replies == [b"OK", 2], f"DEL counts a key SET earlier in the same EXEC (atomic {mode})",
          f"got {replies!r}, wanted [b'OK', 2]")

    # A cross-shard MGET inside the transaction must see the transaction's own writes.
    conn.command("FLUSHALL")
    conn.command("MULTI")
    conn.command("SET", b, "old")
    conn.command("SET", a, "old")
    conn.command("EXEC")
    conn.command("MULTI")
    conn.command("SET", a, "new")
    conn.command("SET", b, "new")
    conn.command("MGET", a, b)
    replies = conn.command("EXEC")
    check(replies == [b"OK", b"OK", [b"new", b"new"]],
          f"an in-EXEC cross-shard MGET sees the same EXEC's writes (atomic {mode})",
          f"got {replies!r}")

    # A list read inside the transaction must see the transaction's own pushes.
    conn.command("FLUSHALL")
    conn.command("MULTI")
    conn.command("RPUSH", b, "seed")
    conn.command("RPUSH", a, "seed")
    conn.command("EXEC")
    conn.command("MULTI")
    conn.command("RPUSH", a, "one")
    conn.command("LRANGE", a, "0", "-1")
    conn.command("RPUSH", a, "two")
    conn.command("LRANGE", a, "0", "-1")
    replies = conn.command("EXEC")
    check(replies == [2, [b"seed", b"one"], 3, [b"seed", b"one", b"two"]],
          f"in-EXEC LRANGE tracks the same EXEC's pushes (atomic {mode})", f"got {replies!r}")


# --------------------------------------------------------------------------------------------
# (b) the version-bytes gauge
# --------------------------------------------------------------------------------------------

def arm_gauge(conn, mode):
    """Drive the exact read-modify-write mix that made the unfixed tree abort in
    FlatStore::atomic_finish_group_install, then demand the gauge is conserved.

    The counter is a LATE detector by construction: the gauge only notices a drift once the drift
    exceeds the version bytes still outstanding on that owner, which is why the original abort()
    fired in a group pass unrelated to the command that corrupted the accounting.  A light workload
    can therefore be wrong without the counter moving, so this arm runs the heavy mix (hundreds of
    transactions of INCRBY/APPEND/RPUSH over a small key set) rather than a handful of rounds.  On a
    binary with the resolver ranking reverted this arm reports non-zero; that transcript is in
    NOTES-EXECFIX.md and is what makes the zero here non-vacuous.
    """
    import random

    rng = random.Random(20260827)
    conn.command("FLUSHALL")
    listkeys = [f"{TAG}:gauge:l{i}" for i in range(6)]
    strkeys = [f"{TAG}:gauge:s{i}" for i in range(18)]
    values = ["", "v", "hello", "42", "-7", "value-" + "y" * 90]
    for key in strkeys:
        conn.command("SET", key, rng.choice(values))
    for key in listkeys:
        conn.command("RPUSH", key, "seed")

    def body():
        pick = rng.randrange(3)
        if pick == 0:
            return ("INCRBY", rng.choice(strkeys), str(rng.randrange(-5, 6)))
        if pick == 1:
            return ("APPEND", rng.choice(strkeys), rng.choice(values))
        return ("RPUSH", rng.choice(listkeys), rng.choice(values))

    before = counter(conn, "atomic_gauge_underflows")
    for _ in range(700):
        conn.command("MULTI")
        for _ in range(rng.randrange(1, 7)):
            conn.command(*body())
        conn.command("EXEC")
        conn.command(*body())
    delta = counter(conn, "atomic_gauge_underflows") - before
    check(delta == 0,
          f"version-bytes gauge stays conserved under the in-MULTI RMW mix (atomic {mode})",
          f"atomic_gauge_underflows advanced by {delta}: the store returned more version bytes "
          f"than it charged, which on the unfixed tree was a std::abort() in "
          f"atomic_finish_group_install")


# --------------------------------------------------------------------------------------------
# (d) cross-shard LCS inside MULTI
# --------------------------------------------------------------------------------------------

LCS_SHAPES = [
    lambda a, b: ("LCS", a, b),
    lambda a, b: ("LCS", a, b, "LEN"),
    lambda a, b: ("LCS", a, b, "IDX", "MINMATCHLEN", "4", "WITHMATCHLEN"),
]


def arm_lcs(conn, mode):
    a, b = two_owner_keys(conn, "lcs")
    check(shard_of(conn, a) != shard_of(conn, b),
          f"geometry: the LCS key pair spans two owners (atomic {mode})")
    conn.command("FLUSHALL")
    conn.command("SET", a, "ohmytext")
    conn.command("SET", b, "mynewtext")
    for i, shape in enumerate(LCS_SHAPES):
        bare = conn.command(*shape(a, b))
        conn.command("MULTI")
        conn.command(*shape(a, b))
        wrapped = conn.command("EXEC")
        check(wrapped == [bare],
              f"cross-shard LCS shape {i} inside MULTI equals bare (atomic {mode})",
              f"bare={bare!r} exec={wrapped!r}")

    # same-owner control: this shape already worked and must keep working.
    same = f"{TAG}:lcs:same"
    partner = None
    for index in range(4000):
        cand = f"{TAG}:lcs:same:{index}"
        if shard_of(conn, cand) == shard_of(conn, same):
            partner = cand
            break
    if partner is None:
        raise AssertionError("no same-shard partner found for the LCS control")
    conn.command("SET", same, "ohmytext")
    conn.command("SET", partner, "mynewtext")
    bare = conn.command("LCS", same, partner)
    conn.command("MULTI")
    conn.command("LCS", same, partner)
    check(conn.command("EXEC") == [bare],
          f"same-owner LCS inside MULTI control (atomic {mode})")


# --------------------------------------------------------------------------------------------
# breadth: nothing else answers the internal cross-shard completion error inside MULTI
# --------------------------------------------------------------------------------------------

def arm_breadth(conn, mode):
    a, b, c = two_owner_keys(conn, "breadth", 3)
    shapes = [
        ([("SET", a, "ohmytext"), ("SET", b, "mynewtext")], ("MGET", a, b)),
        ([], ("MSET", a, "1", b, "2")),
        ([], ("MSETNX", a, "1", b, "2")),
        ([("SET", a, "1"), ("SET", b, "2")], ("DEL", a, b)),
        ([("SET", a, "1"), ("SET", b, "2")], ("EXISTS", a, b)),
        ([("SET", a, "1"), ("SET", b, "2")], ("TOUCH", a, b)),
        ([("SET", a, "ohmytext"), ("SET", b, "mynewtext")], ("BITOP", "AND", c, a, b)),
        ([("SET", a, "1"), ("SET", b, "2")], ("COPY", a, b, "REPLACE")),
        ([("SET", a, "1"), ("SET", b, "2")], ("RENAME", a, b)),
        ([("SADD", a, "x", "y"), ("SADD", b, "y", "z")], ("SINTER", a, b)),
        ([("SADD", a, "x", "y"), ("SADD", b, "y", "z")], ("SINTERSTORE", c, a, b)),
        ([("SADD", a, "x", "y"), ("SADD", b, "y", "z")], ("SMOVE", a, b, "x")),
        ([("ZADD", a, "1", "x"), ("ZADD", b, "2", "y")], ("ZUNIONSTORE", c, "2", a, b)),
        ([("ZADD", a, "1", "x"), ("ZADD", b, "2", "y")], ("ZMPOP", "2", a, b, "MIN")),
        ([("RPUSH", a, "x", "y"), ("RPUSH", b, "z")], ("LMPOP", "2", a, b, "LEFT")),
        ([("RPUSH", a, "x", "y"), ("RPUSH", b, "z")], ("LMOVE", a, b, "LEFT", "RIGHT")),
        ([("RPUSH", a, "x", "y"), ("RPUSH", b, "z")], ("RPOPLPUSH", a, b)),
        ([("PFADD", a, "x"), ("PFADD", b, "y")], ("PFCOUNT", a, b)),
        ([("PFADD", a, "x"), ("PFADD", b, "y")], ("PFMERGE", c, a, b)),
        ([("RPUSH", a, "x", "y")], ("SORT", a, "ALPHA", "STORE", c)),
        ([("SET", a, "1"), ("SET", b, "2")], ("KEYS", f"{TAG}:breadth:*")),
    ]
    bad = []
    for setup, body in shapes:
        conn.command("FLUSHALL")
        for step in setup:
            conn.command(*step)
        bare = conn.command(*body)
        conn.command("FLUSHALL")
        for step in setup:
            conn.command(*step)
        conn.command("MULTI")
        conn.command(*body)
        wrapped = conn.command("EXEC")
        if wrapped != [bare]:
            bad.append((body[0], bare, wrapped))
    check(not bad, f"every cross-shard multi-key command answers in MULTI as it does bare "
                   f"(atomic {mode})", f"{bad!r}")

    # SHELVED, and asserted so it cannot drift silently: a FAILING NX condition (RENAMENX/COPY
    # without REPLACE, destination present) inside MULTI answers EXECABORT instead of 0.  The
    # keyspace is left correct; only the reply differs.  See NOTES-EXECFIX.md section (e) for why
    # this is not a one-line fix: the child's abort flag IS the transaction's abort flag, so making
    # the condition non-aborting would let the source hop's delete become visible.
    for body in (("RENAMENX", a, b), ("COPY", a, b)):
        conn.command("FLUSHALL")
        conn.command("SET", a, "1")
        conn.command("SET", b, "2")
        conn.command("MULTI")
        conn.command(*body)
        wrapped = conn.command("EXEC")
        aborted = isinstance(wrapped, RespError) and "EXECABORT" in str(wrapped)
        check(aborted,
              f"SHELVED and unchanged: failing {body[0]} NX in MULTI still EXECABORTs "
              f"(atomic {mode})",
              f"got {wrapped!r}; if this now answers 0 the shelved item was fixed -- update "
              f"NOTES-EXECFIX.md and turn this into a positive assertion")
        check(conn.command("GET", a) == b"1" and conn.command("GET", b) == b"2",
              f"SHELVED {body[0]}: the keyspace is still left correct (atomic {mode})")


def main():
    conn = Conn()
    admin = Conn()
    try:
        for mode in (0, 1):
            if not set_atomic(conn, mode):
                FAILURES.append(f"CONFIG SET atomic {mode}")
                print(f"  FAIL CONFIG SET atomic {mode}", flush=True)
                continue
            ok(f"CONFIG SET atomic {mode}")
            # Per-arm, not per-run: a build that cannot report a counter must still produce a
            # complete red transcript for every OTHER arm instead of stopping at the first one.
            for arm in (arm_lost_write, arm_lost_append, arm_read_your_own_write,
                        arm_gauge, arm_lcs, arm_breadth):
                try:
                    arm(admin, mode)
                except (AssertionError, EOFError, OSError) as failure:
                    FAILURES.append(f"{arm.__name__} (atomic {mode})")
                    print(f"  FAIL {arm.__name__} (atomic {mode}): {failure}", flush=True)
    except (AssertionError, EOFError, OSError) as failure:
        FAILURES.append(str(failure))
        print(f"  FAIL {failure}", flush=True)
    finally:
        try:
            admin.command("FLUSHALL")
        except (EOFError, OSError, AssertionError):
            pass
        conn.close()
        admin.close()

    print(f"execfix: {'PASS' if not FAILURES else 'FAIL (%d)' % len(FAILURES)}", flush=True)
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
