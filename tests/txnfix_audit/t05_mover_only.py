# T05: atomic-ON cross-shard movers racing ONLY each other (no other writer). W threads each
# move a disjoint member/element range from the same src to the same dst.
# SMOVE: members are conserved: SCARD(src)+SCARD(dst) == N and SCARD(dst) == acked moves.
# RPOPLPUSH: elements conserved: LLEN(src)+LLEN(dst) == N and LLEN(dst) == acked pops.
# Usage: t05_mover_only.py <port> <tomo|oracle> <atomic> <mode> <smove|rpoplpush> [N] [W]
import sys, threading, time
from resp import *
port = int(sys.argv[1]); which = sys.argv[2]; atomic = sys.argv[3]; mode = sys.argv[4]; kind = sys.argv[5]
N = int(sys.argv[6]) if len(sys.argv) > 6 else 2000
W = int(sys.argv[7]) if len(sys.argv) > 7 else 4
if which == "oracle":
    srv = Server(port, oracle=True, cpus=CPUS)
else:
    srv = Server(port, ["--thread-mode", mode, "--atomic", atomic, "--enable-debug-command", "yes"], cpus=CPUS)
try:
    c = srv.conn(timeout=60)
    if which != "oracle":
        cands = ["q:%d" % i for i in range(400)]
        geo = c.cmd("DEBUG", "SHARDS", *cands)
        owner = {cands[i]: geo[i][1] for i in range(len(cands))}
        src = cands[0]; dst = next(k for k in cands if owner[k] != owner[src])
    else:
        src, dst = "q:0", "q:1"
    c.cmd("DEL", src, dst)
    for i in range(0, N, 500):
        batch = ["e%d" % j for j in range(i, min(N, i + 500))]
        c.cmd("SADD" if kind == "smove" else "RPUSH", src, *batch)
    acked = [0]; errs = []
    lock = threading.Lock()
    def mover(lo, hi):
        x = srv.conn(timeout=60)
        n = 0
        for j in range(lo, hi):
            r = x.cmd("SMOVE", src, dst, "e%d" % j) if kind == "smove" else x.cmd("RPOPLPUSH", src, dst)
            if (kind == "smove" and r == 1) or (kind != "smove" and isinstance(r, bytes)): n += 1
            elif isinstance(r, RespError): errs.append(r)
        with lock: acked[0] += n
        x.close()
    step = N // W
    ts = [threading.Thread(target=mover, args=(w * step, (w + 1) * step)) for w in range(W)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    if kind == "smove":
        a, b = c.cmd("SCARD", src), c.cmd("SCARD", dst)
    else:
        a, b = c.cmd("LLEN", src), c.cmd("LLEN", dst)
    print("%s atomic=%s mode=%s %s N=%d W=%d: acked=%d  src=%d dst=%d  src+dst=%d (must be %d)  dst-vs-acked=%d  errors=%d %.1fs"
          % (which, atomic, mode, kind, N, W, acked[0], a, b, a + b, N, b - acked[0], len(errs), time.time() - t0))
    c.close()
finally:
    print("server rc", srv.stop())
