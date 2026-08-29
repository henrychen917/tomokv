#!/usr/bin/env python3
"""Glob and scan-grammar parity, checked against a live Redis oracle.

usage: globcase.py THOST TPORT OHOST OPORT

Every assertion here is differential: the same bytes go to tomokv and to redis 7.4.x and the two
replies must agree. That matters more than a hand-written expectation, because the failures this
covers are all cases where tomokv was *self-consistent* and merely disagreed with redis.

The ACL case is the reason this file exists. `command_glob_match` matched case-INSENSITIVELY, so a
grant of `~USER:*` also granted `user:*` -- a silent permission WIDENING, invisible to any test that
only checks that granted keys work. So the ACL check below carries a negative control: a key outside
the pattern must be refused. Without it, a server whose ACL layer had stopped enforcing entirely
would pass the widening test by accident, which is the vacuous-validation trap.
"""

import socket
import sys

THOST, TPORT, OHOST, OPORT = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])

PASS = FAIL = 0


class Conn:
    def __init__(self, host, port):
        self.sock = socket.create_connection((host, port), timeout=10)
        self.file = self.sock.makefile("rb")

    def cmd(self, *args):
        enc = [a if isinstance(a, bytes) else str(a).encode() for a in args]
        self.sock.sendall(b"*%d\r\n" % len(enc) +
                          b"".join(b"$%d\r\n" % len(a) + a + b"\r\n" for a in enc))
        return self._read()

    def _read(self):
        prefix = self.file.read(1)
        line = self.file.readline()
        if not prefix:
            raise AssertionError("connection closed mid-reply")
        value = line[:-2]
        if prefix in b"+:,#":
            return value
        if prefix == b"-":
            # Only the error CLASS is comparable: redis and tomokv legitimately word the tail of a
            # message differently, but the leading token is protocol.
            return b"ERRCLASS:" + value.split(b" ")[0]
        if prefix == b"$":
            n = int(value)
            if n == -1:
                return None
            payload = self.file.read(n)
            self.file.read(2)
            return payload
        if prefix == b"*":
            n = int(value)
            return None if n == -1 else [self._read() for _ in range(n)]
        raise AssertionError("unknown RESP prefix %r" % prefix)


def check(name, got, want, got_label="tomokv", want_label="redis"):
    global PASS, FAIL
    if got == want:
        PASS += 1
        print("  ok   %-46s %r" % (name, got))
    else:
        FAIL += 1
        print("  FAIL %-46s %s=%r %s=%r" % (name, got_label, got, want_label, want))


def scan_all(conn, pattern):
    """SCAN is INCREMENTAL: one call returns one shard's slice plus a non-zero cursor. Comparing a
    single SCAN call against KEYS compares a partial result against a complete one and 'finds' a
    divergence that does not exist -- iterate to cursor 0."""
    cursor, out = b"0", []
    while True:
        reply = conn.cmd("SCAN", cursor, "MATCH", pattern, "COUNT", "1000")
        if not isinstance(reply, list) or len(reply) != 2:
            return reply           # an error reply: hand it back for a differential comparison
        cursor, keys = reply[0], reply[1] or []
        out.extend(keys)
        if cursor == b"0":
            return sorted(out)


def differential(name, *args, sort=False):
    """Send identical bytes to both servers; the replies must match."""
    g, w = T.cmd(*args), O.cmd(*args)
    if sort and isinstance(g, list) and isinstance(w, list):
        g, w = sorted(g), sorted(w)
    check(name, g, w)


T, O = Conn(THOST, TPORT), Conn(OHOST, OPORT)
for c in (T, O):
    c.cmd("FLUSHALL")

# ---------------------------------------------------------------- D1: ACL key-pattern case
# Redis key patterns are case SENSITIVE. A grant of ~USER:* must not reach user:*.
for c in (T, O):
    c.cmd("ACL", "SETUSER", "globt", "on", ">pw", "~USER:*", "+@all")
    c.cmd("SET", "USER:1", "granted")
    c.cmd("SET", "user:1", "must-not-be-readable")
    c.cmd("SET", "other:1", "control")

TU, OU = Conn(THOST, TPORT), Conn(OHOST, OPORT)
TU.cmd("AUTH", "globt", "pw")
OU.cmd("AUTH", "globt", "pw")
tg, og = TU.cmd("GET", "USER:1"), OU.cmd("GET", "USER:1")
check("ACL ~USER:* grants USER:1", tg, og)
# The widening itself.
tw, ow = TU.cmd("GET", "user:1"), OU.cmd("GET", "user:1")
check("ACL ~USER:* REFUSES user:1 (case)", tw, ow)
# Negative control: proves the ACL layer is enforcing at all, so the line above cannot pass vacuously.
tc, oc = TU.cmd("GET", "other:1"), OU.cmd("GET", "other:1")
check("ACL negative control refuses other:1", tc, oc)
if tc != b"ERRCLASS:NOPERM":
    print("  FAIL %-46s control did not deny; every ACL row above is vacuous" % "ACL enforcement live")
    FAIL += 1

# ---------------------------------------------------------------- D1: PSUBSCRIBE delivery case
for c in (T, O):
    c.cmd("FLUSHALL")
subs = {}
for tag, host, port in (("tomokv", THOST, TPORT), ("redis", OHOST, OPORT)):
    s = Conn(host, port)
    s.cmd("PSUBSCRIBE", "News.*")
    subs[tag] = s
T.cmd("PUBLISH", "news.x", "lower")
T.cmd("PUBLISH", "News.x", "upper")
O.cmd("PUBLISH", "news.x", "lower")
O.cmd("PUBLISH", "News.x", "upper")
delivered = {}
for tag, s in subs.items():
    s.sock.settimeout(1.0)
    chans = []
    try:
        while True:
            msg = s._read()
            if isinstance(msg, list) and msg and msg[0] == b"pmessage":
                chans.append(msg[2])
    except (socket.timeout, AssertionError):
        pass
    delivered[tag] = sorted(chans)
check("PSUBSCRIBE News.* delivery is case-sensitive", delivered["tomokv"], delivered["redis"])

# ---------------------------------------------------------------- D2/D3: glob grammar, KEYS vs SCAN
for c in (T, O):
    c.cmd("FLUSHALL")
    for k in ("abc", "a", "b", "z", "azb", "a]b", "aXb"):
        c.cmd("SET", k, "v")

PATTERNS = [b"[abc", b"[z-a]", b"[a-\xff]", b"[!a]", b"[^a]", b"a*b", b"[a-c]", b"?"]
for pat in PATTERNS:
    differential("KEYS %r" % pat, "KEYS", pat, sort=True)
    # Cursor VALUES are not comparable across servers -- tomokv shards its cursor space and redis
    # does not -- so compare the fully-iterated key SETS, which are the actual contract.
    check("SCAN %r" % pat, scan_all(T, pat), scan_all(O, pat))
    # KEYS and SCAN run two different matchers in this tree, so they must be compared to each other
    # as well as to redis -- a shared wrong answer would pass the differential rows above.
    check("KEYS==SCAN for %r" % pat,
          sorted(T.cmd("KEYS", pat) or []), scan_all(T, pat),
          got_label="KEYS", want_label="SCAN")

# ---------------------------------------------------------------- D4: cursor grammar agreement
# Redis parses cursors with the strtoul family, which ACCEPTS leading whitespace, a leading '+',
# leading zeroes and '-0'. Only the accept/reject decision is comparable: the cursor VALUE a server
# hands back is its own business (tomokv shards its cursor space), so compare rejection only.
for c, k in ((T, "gs"), (O, "gs")):
    pass
for c in (T, O):
    c.cmd("SADD", "gset", "m1")
    c.cmd("HSET", "ghash", "f", "v")
    c.cmd("ZADD", "gzset", "1", "m")


def rejected(reply):
    return isinstance(reply, bytes) and reply.startswith(b"ERRCLASS:")


for cur in (b" 5", b"+5", b"05", b"-0", b"abc"):
    for name, args in (("SSCAN", ("SSCAN", "gset", cur)),
                       ("HSCAN", ("HSCAN", "ghash", cur)),
                       ("ZSCAN", ("ZSCAN", "gzset", cur)),
                       ("SCAN ", ("SCAN", cur))):
        check("%s cursor %r rejected?" % (name, cur),
              rejected(T.cmd(*args)), rejected(O.cmd(*args)))

# ---------------------------------------------------------------- D5: NOVALUES only on HSCAN
# Fresh keys of the right type -- a leftover string under these names answers WRONGTYPE and the row
# would pass while never reaching the NOVALUES check at all.
differential("ZSCAN rejects NOVALUES", "ZSCAN", "gzset", "0", "NOVALUES")
differential("SSCAN rejects NOVALUES", "SSCAN", "gset", "0", "NOVALUES")
differential("SCAN  rejects NOVALUES", "SCAN", "0", "NOVALUES")
differential("HSCAN accepts NOVALUES", "HSCAN", "ghash", "0", "NOVALUES")

# ---------------------------------------------------------------- D6: count grammar agreement
# ACL LOG entries embed client-info, which legitimately differs between the two servers, so compare
# only the accept/reject decision and the number of entries returned.
for n in (b"05", b"-0", b"+1", b"1", b"0"):
    tg, og = T.cmd("ACL", "LOG", n), O.cmd("ACL", "LOG", n)
    check("ACL LOG %r rejected?" % n, rejected(tg), rejected(og))
    if not rejected(tg) and not rejected(og):
        check("ACL LOG %r entry count" % n, len(tg), len(og))
    differential("SLOWLOG GET %r" % n, "SLOWLOG", "GET", n)

print("globcase: %d ok, %d FAIL" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
