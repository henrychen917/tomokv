#!/usr/bin/env python3
"""CLIENT REPLY OFF/SKIP must suppress a cross-shard MGET reply COMPLETELY.

    tests/replyoff_xshard.py HOST PORT

The cross-shard retire hook assembles an MGET whose values are borrowed (>= min(zc-min, 1024)
bytes) straight into the connection's segment queue -- array header, borrowed bulks, CRLFs --
BEFORE the suppressing serve consults the op's skip mark. Pre-fix only the op's TAIL was dropped:
the header and the bulks reached the wire, the peer parsed the next real reply as the array's
missing element, and every later reply on the connection was shifted by one.

Vacuity guards (a run that exercises nothing must FAIL):
  - zero-copy is enabled on this boot (CONFIG GET zc-min > 0): with it every 4KB value in a
    cross-shard MGET is gathered as a BORROW (cutover = min(zc-min, 1024));
  - the REPLY ON control MGET returns every value intact and moves zc_sends (the borrow path
    really fired: an MGET borrows only through the cross-shard gather, so this also proves the
    32 random keys spanned shards);
  - the suppressed MGET moves zc_releases (borrows were gathered and returned UNSENT) and does
    NOT move zc_sends (nothing borrowed was submitted).
Exit status is the number of failed checks.
"""
import os
import socket
import sys
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
NKEYS, VALUE_LEN = 32, 4096
FAIL = 0


def check(ok, label, detail=""):
    global FAIL
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' -- ' + detail) if (detail and not ok) else ''}")
    if not ok:
        FAIL += 1


def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        out.append(b"$%d\r\n%s\r\n" % (len(b), b))
    return b"".join(out)


class Conn:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=10)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.s.makefile("rb", buffering=0)

    def send(self, *args):
        self.s.sendall(enc(*args))

    def read(self):
        line = self.f.readline()
        if not line:
            raise EOFError("connection closed")
        t = line[:1]
        if t in b"+-:":
            return line
        if t == b"$":
            n = int(line[1:-2])
            return None if n < 0 else self.f.read(n + 2)[:-2]
        if t == b"*":
            n = int(line[1:-2])
            return None if n < 0 else [self.read() for _ in range(n)]
        raise RuntimeError(f"unexpected reply head {line!r}")

    def cmd(self, *args):
        self.send(*args)
        return self.read()

    # Exactly `want` bytes must arrive, then NOTHING else within `quiet` seconds.
    def expect_wire(self, want, quiet=0.3):
        self.s.settimeout(5)
        got = b""
        try:
            while len(got) < len(want):
                chunk = self.s.recv(65536)
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            pass
        extra = b""
        self.s.settimeout(quiet)
        try:
            extra = self.s.recv(65536)
        except socket.timeout:
            pass
        self.s.settimeout(10)
        return got, extra


def info_stats(c):
    raw = c.cmd("INFO", "STATS")
    out = {}
    for line in raw.decode(errors="replace").split("\r\n"):
        if ":" in line and not line.startswith("#"):
            k, _, v = line.partition(":")
            out[k] = v
    return out


def stat(c, key):
    return int(info_stats(c).get(key, "0"))


admin = Conn()
zc = admin.cmd("CONFIG", "GET", "zc-min")
zc_min = int(zc[1]) if isinstance(zc, list) and len(zc) == 2 else 0
check(zc_min > 0, "boot has zero-copy enabled (borrowed MGET values are reachable)",
      f"zc-min={zc_min}")

tag = os.urandom(4).hex()
keys = [f"replyoff:{tag}:{i}" for i in range(NKEYS)]
values = [os.urandom(VALUE_LEN) for _ in range(NKEYS)]
for k, v in zip(keys, values):
    assert admin.cmd("SET", k, v) == b"+OK\r\n"

# ---- control: REPLY ON, the same MGET must answer in full and move zc_sends ----------------------
c = Conn()
zc_sends0 = stat(admin, "zc_sends")
reply = c.cmd("MGET", *keys)
check(reply == values, "control MGET (REPLY ON) returns every value intact")
zc_sends1 = stat(admin, "zc_sends")
check(zc_sends1 > zc_sends0, "control MGET borrowed its values (zc_sends moved)",
      f"{zc_sends0} -> {zc_sends1}: boot with zero-copy enabled")

# ---- REPLY OFF: nothing until REPLY ON's +OK, then +PONG, then silence -------------------------
zc_sends0, zc_rel0 = stat(admin, "zc_sends"), stat(admin, "zc_releases")
c.send("CLIENT", "REPLY", "OFF")
c.send("MGET", *keys)
c.send("CLIENT", "REPLY", "ON")
c.send("PING")
got, extra = c.expect_wire(b"+OK\r\n+PONG\r\n")
check(got == b"+OK\r\n+PONG\r\n" and not extra,
      "REPLY OFF: cross-shard MGET leaves NOTHING on the wire",
      f"got={got[:64]!r}{'...' if len(got) > 64 else ''} extra={len(extra)}B")
zc_sends1, zc_rel1 = stat(admin, "zc_sends"), stat(admin, "zc_releases")
check(zc_rel1 > zc_rel0, "suppressed MGET returned its borrows (zc_releases moved)",
      f"{zc_rel0} -> {zc_rel1}")
check(zc_sends1 == zc_sends0, "suppressed MGET submitted no borrowed send (zc_sends unchanged)",
      f"{zc_sends0} -> {zc_sends1}")

# ---- REPLY SKIP: the MGET is skipped, PING answers, then silence --------------------------------
c.send("CLIENT", "REPLY", "SKIP")
c.send("MGET", *keys)
c.send("PING")
got, extra = c.expect_wire(b"+PONG\r\n")
check(got == b"+PONG\r\n" and not extra,
      "REPLY SKIP: cross-shard MGET leaves NOTHING on the wire",
      f"got={got[:64]!r}{'...' if len(got) > 64 else ''} extra={len(extra)}B")

# ---- the connection is still in sync afterwards --------------------------------------------------
check(c.cmd("GET", keys[0]) == values[0], "connection still in sync after suppression")
check(c.cmd("MGET", *keys) == values, "a later REPLY ON MGET on the same connection is intact")

for k in keys:
    admin.cmd("DEL", k)
print(f"replyoff_xshard: {FAIL} failed")
sys.exit(FAIL)
