# T04: no debug hook. atomic-ON cross-shard SMOVE stream vs a concurrent SADD stream into the same
# destination. Exact accounting: SCARD(dst) must equal moved + added. Also EXEC/INCR counter at
# the same time is NOT run here (see T01). Usage: t04_mover_stress.py <port> <tomo|oracle> <atomic> <mode> [N]
import sys, threading, time
from resp import *
port = int(sys.argv[1]); which = sys.argv[2]; atomic = sys.argv[3]; mode = sys.argv[4]
N = int(sys.argv[5]) if len(sys.argv) > 5 else 3000
if which == "oracle":
    srv = Server(port, oracle=True, cpus=CPUS)
else:
    srv = Server(port, ["--thread-mode", mode, "--atomic", atomic, "--enable-debug-command", "yes"], cpus=CPUS)
try:
    c = srv.conn(timeout=60)
    if which != "oracle":
        cands = ["s:%d" % i for i in range(400)]
        geo = c.cmd("DEBUG", "SHARDS", *cands)
        owner = {cands[i]: geo[i][1] for i in range(len(cands))}
        src = cands[0]; dst = next(k for k in cands if owner[k] != owner[src])
    else:
        src, dst = "s:0", "s:1"
    c.cmd("DEL", src, dst)
    for i in range(0, N, 500):
        c.cmd("SADD", src, *["m%d" % j for j in range(i, min(N, i + 500))])
    errs = []; moved = [0]; added = [0]
    def mover(lo, hi):
        x = srv.conn(timeout=60)
        for j in range(lo, hi):
            r = x.cmd("SMOVE", src, dst, "m%d" % j)
            if r == 1: moved[0] += 1
            elif r != 0: errs.append(r)
        x.close()
    def adder(lo, hi):
        x = srv.conn(timeout=60)
        for j in range(lo, hi):
            r = x.cmd("SADD", dst, "z%d" % j)
            if r == 1: added[0] += 1
            elif r != 0: errs.append(r)
        x.close()
    W = 4; step = N // W
    ts = [threading.Thread(target=mover, args=(w * step, (w + 1) * step)) for w in range(W)] + \
         [threading.Thread(target=adder, args=(w * step, (w + 1) * step)) for w in range(W)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    card = c.cmd("SCARD", dst); srccard = c.cmd("SCARD", src)
    exp = moved[0] + added[0]
    print("%s atomic=%s mode=%s N=%d: acked moves=%d acked adds=%d SCARD(dst)=%d expected %d (missing %d) SCARD(src)=%d errors=%d %.1fs"
          % (which, atomic, mode, N, moved[0], added[0], card, exp, exp - card, srccard, len(errs), time.time() - t0))
    c.close()
finally:
    print("server rc", srv.stop())

assert not errs and card == exp and srccard + moved[0] == N, "members lost or duplicated"
