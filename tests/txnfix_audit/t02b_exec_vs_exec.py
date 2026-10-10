# T02b: EXEC-vs-EXEC variant of T02 (the racing writer is a single-owner `MULTI; INCR k1; EXEC`). DEBUG ATOMIC-COMMIT-DELAY stalls the transaction's
# finalizer between ticket reserve and epoch store; a plain INCR on the transaction's key that
# lives on the OTHER executor runs inside that window. Redis: k1 == 2 always.
# Usage: t02_exec_directed.py <port> <atomic 0|1> <mode 2s|1s> [rounds]
import sys, threading, time
from resp import *
port = int(sys.argv[1]); atomic = sys.argv[2]; mode = sys.argv[3]
rounds = int(sys.argv[4]) if len(sys.argv) > 4 else 10
srv = Server(port, ["--thread-mode", mode, "--atomic", atomic, "--enable-debug-command", "yes"],
             cpus=CPUS)
try:
    c = srv.conn(timeout=30)
    cands = ["key:%d" % i for i in range(400)]
    geo = c.cmd("DEBUG", "SHARDS", *cands)
    owner = {cands[i]: geo[i][1] for i in range(len(cands))}
    lost = 0; results = []
    for r in range(rounds):
        k1 = cands[2 * r]
        k2 = next(k for k in cands if owner[k] != owner[k1])
        c.cmd("SET", k1, 0); c.cmd("SET", k2, 0)
        c.cmd("DEBUG", "ATOMIC-COMMIT-DELAY", 300000)
        x = srv.conn(timeout=30); y = srv.conn(timeout=30)
        x.send_many([["MULTI"], ["INCR", k1], ["INCR", k2], ["EXEC"]])
        time.sleep(0.05)
        t0 = time.time(); ry = y.pipeline([["MULTI"], ["INCR", k1], ["EXEC"]])[2]; ty = time.time() - t0
        rx = [x.read() for _ in range(4)]
        c.cmd("DEBUG", "ATOMIC-COMMIT-DELAY", 0)
        v1 = int(c.cmd("GET", k1)); v2 = int(c.cmd("GET", k2))
        results.append((k1, owner[k1], k2, owner[k2], rx[3], ry, round(ty, 3), v1, v2))
        if v1 != 2: lost += 1
        x.close(); y.close()
    for row in results: print("k1=%s(ex%d) k2=%s(ex%d) EXEC=%s INCR=%s incr_latency=%ss -> GET k1=%d GET k2=%d" % row)
    print("atomic=%s mode=%s: rounds=%d, rounds with a lost INCR (k1 != 2): %d" % (atomic, mode, rounds, lost))
    i = info(c)
    print("atomic_commit_windows", i.get("atomic_commit_windows"), "atomic_groups", i.get("atomic_groups"))
    c.close()
finally:
    print("server rc", srv.stop())

assert lost == 0, "acknowledged INCR lost"
