# T15: no debug hook. C clients each run N `MULTI; INCR k1; INCR k2; EXEC` (k1/k2 on different
# executors). Only EXECs write. Exact accounting: k1 == k2 == C*N. Also checks reply uniqueness:
# every EXEC's INCR k2 result must be distinct (a serial history hands out 1..C*N exactly once).
import sys, threading, time, collections
from resp import *
port = int(sys.argv[1]); which = sys.argv[2]; mode = sys.argv[3]; C = int(sys.argv[4]); N = int(sys.argv[5])
P = int(sys.argv[6]) if len(sys.argv) > 6 else 1
if which == "oracle":
    srv = Server(port, oracle=True, cpus=CPUS)
else:
    srv = Server(port, ["--thread-mode", mode, "--enable-debug-command", "yes"], cpus=CPUS)
try:
    c = srv.conn(timeout=60)
    if which != "oracle":
        cands = ["x%d" % i for i in range(1, 400)]
        geo = c.cmd("DEBUG", "SHARDS", *cands)
        owner = {cands[i]: geo[i][1] for i in range(len(cands))}
        k1 = cands[0]; k2 = next(k for k in cands[1:] if owner[k] != owner[k1])
    else:
        k1, k2 = "x1", "x2"
    c.cmd("SET", k1, 0); c.cmd("SET", k2, 0)
    seen = collections.Counter(); lock = threading.Lock()
    def worker():
        x = srv.conn(timeout=120); local = []
        for _ in range(N // P):
            cmds = []
            for _ in range(P): cmds += [["MULTI"], ["INCR", k1], ["INCR", k2], ["EXEC"]]
            rs = x.pipeline(cmds)
            for j in range(P):
                r = rs[4 * j + 3]
                if isinstance(r, list): local.append(r[1])
        with lock: seen.update(local)
        x.close()
    ts = [threading.Thread(target=worker) for _ in range(C)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    v1, v2 = int(c.cmd("GET", k1)), int(c.cmd("GET", k2))
    dup = sum(n - 1 for n in seen.values() if n > 1)
    print("%s mode=%s C=%d N=%d P=%d: k1=%d k2=%d expected %d each; lost k1=%d k2=%d; duplicated INCR k2 replies=%d  %.1fs"
          % (which, mode, C, N, P, v1, v2, C * N, C * N - v1, C * N - v2, dup, time.time() - t0))
    c.close()
finally:
    print("server rc", srv.stop())

assert (v1, v2, dup, sum(seen.values())) == (C*N, C*N, 0, C*N), "lost or duplicated INCR"
