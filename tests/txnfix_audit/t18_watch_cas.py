# T18: the canonical WATCH/MULTI/EXEC optimistic-increment loop. C clients each perform N
# successful CAS increments: WATCH k; v = GET k; MULTI; SET k v+1; INCR k2(other executor); EXEC
# (retry on nil). Redis: k == C*N and every successful EXEC saw a distinct v.
import sys, threading, collections, time
from resp import *
port = int(sys.argv[1]); which = sys.argv[2]; mode = sys.argv[3]; C = int(sys.argv[4]); N = int(sys.argv[5])
if which == "oracle":
    srv = Server(port, oracle=True, cpus=CPUS)
else:
    srv = Server(port, ["--thread-mode", mode, "--enable-debug-command", "yes"], cpus=CPUS)
try:
    c = srv.conn(timeout=60)
    if which != "oracle":
        cands = ["c%d" % i for i in range(1, 400)]
        geo = c.cmd("DEBUG", "SHARDS", *cands)
        owner = {cands[i]: geo[i][1] for i in range(len(cands))}
        k = cands[0]; k2 = next(x for x in cands[1:] if owner[x] != owner[k])
    else:
        k, k2 = "c1", "c2"
    c.cmd("SET", k, 0); c.cmd("SET", k2, 0)
    seen = collections.Counter(); retries = [0]; lock = threading.Lock()
    def worker():
        x = srv.conn(timeout=120); got = []; r_ = 0
        while len(got) < N:
            x.cmd("WATCH", k)
            v = int(x.cmd("GET", k))
            res = x.pipeline([["MULTI"], ["SET", k, v + 1], ["INCR", k2], ["EXEC"]])[3]
            if res is None: r_ += 1; continue
            got.append(v)
        with lock: seen.update(got); retries[0] += r_
        x.close()
    ts = [threading.Thread(target=worker) for _ in range(C)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    vk, vk2 = int(c.cmd("GET", k)), int(c.cmd("GET", k2))
    dup = sum(n - 1 for n in seen.values() if n > 1)
    print("%s mode=%s C=%d N=%d: k=%d k2=%d expected %d; duplicate observed v=%d; aborted retries=%d %.1fs"
          % (which, mode, C, N, vk, vk2, C * N, dup, retries[0], time.time() - t0))
    c.close()
finally:
    print("server rc", srv.stop())
