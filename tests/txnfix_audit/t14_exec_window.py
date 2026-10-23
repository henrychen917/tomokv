# T14 (round-3 AT12): at --atomic 0, EXEC is admitted through the atomics window
# (min(16*shards,1024) = 256 at 16 shards). 400 connections each send one cross-owner EXEC at once
# while DEBUG ATOMIC-COMMIT-DELAY slows commits; INFO atomic_window_stalls / atomic_groups move.
import sys, threading, time
from resp import *
port = int(sys.argv[1]); atomic = sys.argv[2] if len(sys.argv) > 2 else "0"
srv = Server(port, ["--thread-mode", "2s", "--atomic", atomic, "--enable-debug-command", "yes", "--maxclients", "2000"], cpus=CPUS)
try:
    c = srv.conn(timeout=60)
    i0 = info(c)
    print("atomic=%s credit_pool(idle)=%s window_stalls=%s groups=%s" % (atomic, i0.get("atomic_credit_pool"), i0.get("atomic_window_stalls"), i0.get("atomic_groups")))
    cands = ["w%d" % i for i in range(1, 400)]
    geo = c.cmd("DEBUG", "SHARDS", *cands)
    owner = {cands[i]: geo[i][1] for i in range(len(cands))}
    k1 = cands[0]; k2 = next(k for k in cands[1:] if owner[k] != owner[k1])
    c.cmd("DEBUG", "ATOMIC-COMMIT-DELAY", 2000)
    conns = [srv.conn(timeout=120) for _ in range(AUDIT_CLIENTS or 400)]
    for x in conns: x.send_many([["MULTI"], ["INCR", k1], ["INCR", k2], ["EXEC"]])
    time.sleep(0.2)
    mid = info(c)
    print("mid-burst: credit_pool=%s inflight=%s window_stalls=%s" % (mid.get("atomic_credit_pool"), mid.get("atomic_inflight"), mid.get("atomic_window_stalls")))
    for x in conns:
        r = [x.read() for _ in range(4)]
    c.cmd("DEBUG", "ATOMIC-COMMIT-DELAY", 0)
    i1 = info(c)
    print("after: window_stalls=%s groups=%s k1=%s k2=%s" % (i1.get("atomic_window_stalls"), i1.get("atomic_groups"), c.cmd("GET", k1), c.cmd("GET", k2)))
    totals = [int(c.cmd("GET", k)) for k in (k1, k2)]
    for x in conns: x.close()
    c.close()
finally:
    print("server rc", srv.stop())

assert totals == [AUDIT_CLIENTS or 400] * 2, ("acknowledged INCR lost", totals)
