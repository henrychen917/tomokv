# T17: queue pattern. Producers enqueue with a transaction that also bumps a stats counter on
# another executor (`MULTI; LPUSH q item; INCR produced; EXEC`), consumers RPOP q concurrently.
# Exactly-once: every produced item is consumed or still queued exactly once. Default --atomic 0.
import sys, threading, time, collections
from resp import *
port = int(sys.argv[1]); which = sys.argv[2]; mode = sys.argv[3] if len(sys.argv) > 3 else "2s"
NP, NC, N = 4, 4, AUDIT_OPERATIONS or 3000
if which == "oracle":
    srv = Server(port, oracle=True, cpus=CPUS)
else:
    srv = Server(port, ["--thread-mode", mode, "--enable-debug-command", "yes"], cpus=CPUS)
try:
    c = srv.conn(timeout=60)
    if which != "oracle":
        cands = ["q%d" % i for i in range(1, 400)]
        geo = c.cmd("DEBUG", "SHARDS", *cands)
        owner = {cands[i]: geo[i][1] for i in range(len(cands))}
        q = cands[0]; ctr = next(k for k in cands[1:] if owner[k] != owner[q])
    else:
        q, ctr = "q1", "q2"
    c.cmd("DEL", q, ctr)
    consumed = collections.Counter(); lock = threading.Lock(); done = [0]
    def producer(p):
        x = srv.conn(timeout=60)
        for i in range(N):
            x.pipeline([["MULTI"], ["LPUSH", q, "p%d-%d" % (p, i)], ["INCR", ctr], ["EXEC"]])
        x.close()
        with lock: done[0] += 1
    def consumer():
        x = srv.conn(timeout=60); local = collections.Counter()
        while True:
            r = x.cmd("RPOP", q)
            if r is None:
                with lock:
                    if done[0] == NP: break
                continue
            local[r] += 1
        with lock: consumed.update(local)
        x.close()
    ts = [threading.Thread(target=producer, args=(p,)) for p in range(NP)] + [threading.Thread(target=consumer) for _ in range(NC)]
    for t in ts: t.start()
    for t in ts: t.join()
    rest = c.cmd("LRANGE", q, 0, -1)
    for r in rest: consumed[r] += 1
    produced = {("p%d-%d" % (p, i)).encode() for p in range(NP) for i in range(N)}
    dup = sum(n - 1 for n in consumed.values() if n > 1)
    missing = len(produced - set(consumed))
    print("%s mode=%s: produced %d (counter %s), consumed+left %d distinct, duplicates %d, missing %d"
          % (which, mode, len(produced), c.cmd("GET", ctr), len(consumed), dup, missing))
    counter_value = int(c.cmd("GET", ctr))
    c.close()
finally:
    print("server rc", srv.stop())

assert not missing and not dup and counter_value == NP*N and set(consumed) == produced, "queue accounting"
