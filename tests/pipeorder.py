#!/usr/bin/env python3
"""Pipelined same-connection program order: a transaction fragment must not run past the
connection's own earlier cross-shard write (the seed-19 differ divergence).  One pipelined
burst per iteration: cross-shard MSET; 5-key cross-shard DEL; MULTI; TYPE; APPEND; EXEC.
Correct: TYPE +none, APPEND :1.  The pre-fix server answered +string/:3 in ~50% of
iterations.  Usage: pipeorder.py PORT [ITERS]"""
import socket, sys, time, select
from contextlib import closing
import _lib
PORT = int(sys.argv[1]); N = int(sys.argv[2]) if len(sys.argv) > 2 else 400
def enc(args):
    out = b"*%d\r\n" % len(args)
    for a in args:
        b = a.encode() if isinstance(a, str) else a
        out += b"$%d\r\n%s\r\n" % (len(b), b)
    return out
def rr(f):
    line = f.readline(); t = line[:1]
    if t in b"+-:": return line
    if t == b"$":
        n = int(line[1:-2])
        return line if n == -1 else line + f.read(n + 2)
    if t == b"*":
        n = int(line[1:-2])
        return line if n == -1 else [rr(f) for _ in range(n)]
    raise RuntimeError(line)
s = socket.create_connection(("127.0.0.1", PORT), timeout=30); s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = s.makefile("rb")
bad = 0
# A held DEL supplies the dangerous predecessor deterministically. Keep the
# original 400 complete pipeline rolls below as additional breadth.
with closing(_lib.Conn("127.0.0.1", PORT)) as admin:
    assert admin.cmd("CONFIG", "GET", "atomic") == [b"atomic", b"1"]
    owners = _lib.owner_buckets(admin, "po:held", per_owner=3)
    first, second = [group for group in owners.values() if len(group) >= 3][:2]
    a, x, y = first[:3]
    m, z, k = second[:3]
    assert admin.cmd("MSET", k, "v", a, "42", m, "hello") == b"OK"
    before = int(_lib.info(admin, "stats")["atomic_exec_order_holds"])
    with _lib.armed(admin, "ATOMIC-COMMIT-HOLD", 1):
        burst = [["DEL", a, x, y, z, m], ["MULTI"], ["TYPE", m],
                 ["APPEND", a, "v"], ["EXEC"]]
        s.sendall(b"".join(enc(o) for o in burst))
        deadline = time.monotonic() + 10
        while int(_lib.info(admin, "stats")["atomic_exec_order_holds"]) == before:
            assert time.monotonic() < deadline, "EXEC never met the held DEL"
            time.sleep(.005)
        assert int(_lib.info(admin, "stats")["atomic_pending_entries"]) > 0
        assert not select.select([s], [], [], 0)[0], "DEL escaped commit hold"
    replies = [rr(f) for _ in burst]
    assert replies == [b":2\r\n", b"+OK\r\n", b"+QUEUED\r\n", b"+QUEUED\r\n",
                       [b"+none\r\n", b":1\r\n"]], replies
    print("pipeorder: held DEL/EXEC window witnessed; exact replies intact")
for it in range(N):
    u = "%05d" % it
    A  = "po:aa%s:" % u + "a"*32
    M8 = "po:mm%s:" % u + "m"*32
    K13= "po:kk%s:" % u + "k"*32
    K = lambda c: "po:%s%s%s:" % (c, c, u) + c*30
    burst = [["MSET", K13, "v", A, "42", M8, "hello"],
             ["DEL", A, K("x"), K("y"), K("z"), M8],
             ["MULTI"], ["TYPE", M8], ["APPEND", A, "v"], ["EXEC"]]
    s.sendall(b"".join(enc(o) for o in burst))
    rs = [rr(f) for _ in burst]
    ex = rs[5]
    if not (isinstance(ex, list) and ex[0] == b"+none\r\n" and ex[1] == b":1\r\n"):
        bad += 1
        if bad <= 3: print("iter %d: %r" % (it, ex))
print("pipeorder: %d/%d stale" % (bad, N))
sys.exit(1 if bad else 0)
