#!/usr/bin/env python3
"""Session-monotonicity hammer: a pipelined GET a; MGET a b pair must never answer the MGET
with an OLDER world than the GET that precedes it on the same connection.

The hazard window (owner-spotted): the MGET's read epoch is pinned at io-side prepare; the
plain GET posted just before it can EXECUTE after that pin and observe a foreign atomic
commit from the (pin, exec] window. If the MGET then resolves at its older epoch, the later
command answers with the older value — time runs backward inside one connection.

Writer thread: atomic MSET a <n> b <n> with a monotone counter (values equal per commit, so
the MGET is also its own torn-check control). Reader: pipelined GET a; MGET a b batches.
  violation:  int(mget_a) < int(get_a)         (later read older — the monotonicity break)
  torn:       mget_a != mget_b                 (must stay 0 — established invariant)
Usage: session_monotonic.py HOST PORT [SECONDS]
"""
import socket
import sys
import threading
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 20.0


def enc(*args):
    out = [b"*%d\r\n" % len(args)]
    for a in args:
        b = a if isinstance(a, bytes) else str(a).encode()
        out += [b"$%d\r\n" % len(b), b, b"\r\n"]
    return b"".join(out)


class Conn:
    def __init__(self):
        self.s = socket.create_connection((HOST, PORT), timeout=10)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.f = self.s.makefile("rb")

    def read_reply(self):
        line = self.f.readline()
        k = line[:1]
        if k in b"+-:":
            return line[1:-2]
        if k == b"$":
            n = int(line[1:-2])
            if n == -1:
                return None
            d = self.f.read(n + 2)
            return d[:-2]
        if k == b"*":
            n = int(line[1:-2])
            return [self.read_reply() for _ in range(n)]
        raise AssertionError("marker %r" % k)


stop = False
violations = []
torn = []
batches = [0]
writes = [0]


def writer():
    c = Conn()
    n = 0
    while not stop:
        n += 1
        c.s.sendall(enc("MSET", "sm:a", n, "sm:b", n))
        c.read_reply()
        writes[0] = n


def reader():
    c = Conn()
    c.s.sendall(enc("MSET", "sm:a", 0, "sm:b", 0))
    c.read_reply()
    while not stop:
        c.s.sendall(enc("GET", "sm:a") + enc("MGET", "sm:a", "sm:b"))
        g = c.read_reply()
        m = c.read_reply()
        batches[0] += 1
        ga = int(g) if g else 0
        ma = int(m[0]) if m and m[0] else 0
        mb = int(m[1]) if m and m[1] else 0
        if ma != mb and len(torn) < 5:
            torn.append((batches[0], ga, ma, mb))
        if ma < ga and len(violations) < 8:
            violations.append((batches[0], ga, ma, mb))


threads = [threading.Thread(target=writer)] + [threading.Thread(target=reader) for _ in range(2)]
for t in threads:
    t.start()
time.sleep(SECONDS)
stop = True
for t in threads:
    t.join()

print("batches=%d writes=%d torn=%d monotonicity_violations=%d" %
      (batches[0], writes[0], len(torn), len(violations)))
for v in violations:
    print("  VIOLATION batch=%d get_a=%d mget=(%d,%d)  <- later read is OLDER" % v)
for v in torn:
    print("  TORN batch=%d get_a=%d mget=(%d,%d)" % v)
sys.exit(1 if (violations or torn) else 0)
