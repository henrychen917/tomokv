# T01: EXEC isolation vs a concurrent plain read-modify-write (lost-update probe).
# E clients loop `MULTI; INCR k1; INCR k2; EXEC` while P clients loop plain `INCR k1`.
# k1 and k2 live on shards owned by DIFFERENT executors (DEBUG SHARDS geometry oracle), so the
# EXEC's install on k1's owner stays undecided until the other owner finalizes the transaction.
# Redis semantics: every acknowledged INCR counts -> k1 == E*N + P*N, k2 == E*N.
# Usage: t01_exec_counter.py <port> <tomo|oracle> <atomic 0|1> <mode 2s|1s> [N]
import sys, threading, time
from resp import *

port = int(sys.argv[1]); which = sys.argv[2]; atomic = sys.argv[3]; mode = sys.argv[4]
N = int(sys.argv[5]) if len(sys.argv) > 5 else 2000
E, P = 4, 4
if which == "oracle":
    srv = Server(port, oracle=True, cpus=CPUS)
else:
    srv = Server(port, ["--thread-mode", mode, "--atomic", atomic, "--enable-debug-command", "yes"],
                 cpus=CPUS)
try:
    c = srv.conn()
    k1, k2 = "k1", None
    if which != "oracle":
        cands = ["k%d" % i for i in range(1, 200)]
        geo = c.cmd("DEBUG", "SHARDS", *cands)
        owner = {cands[i]: geo[i][1] for i in range(len(cands))}
        k1 = cands[0]
        k2 = next(k for k in cands[1:] if owner[k] != owner[k1])
        print("geometry", k1, geo[0], k2, geo[cands.index(k2)])
    else:
        k2 = "k2"
    c.cmd("SET", k1, 0); c.cmd("SET", k2, 0)
    before = info(c) if which != "oracle" else {}
    errors = []
    def exec_loop():
        x = srv.conn(timeout=60)
        try:
            for _ in range(N):
                r = x.pipeline([["MULTI"], ["INCR", k1], ["INCR", k2], ["EXEC"]])
                if not (isinstance(r[3], list) and len(r[3]) == 2):
                    errors.append(("exec", r))
        except Exception as e:
            errors.append(("exec-exc", repr(e)))
        x.close()
    def incr_loop():
        x = srv.conn(timeout=60)
        try:
            for _ in range(N):
                r = x.cmd("INCR", k1)
                if not isinstance(r, int): errors.append(("incr", r))
        except Exception as e:
            errors.append(("incr-exc", repr(e)))
        x.close()
    ts = [threading.Thread(target=exec_loop) for _ in range(E)] + \
         [threading.Thread(target=incr_loop) for _ in range(P)]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    dt = time.time() - t0
    v1 = int(c.cmd("GET", k1)); v2 = int(c.cmd("GET", k2))
    exp1, exp2 = E * N + P * N, E * N
    print("%s atomic=%s mode=%s N=%d: k1=%d (expected %d, lost %d)  k2=%d (expected %d, lost %d)  errors=%d  %.1fs"
          % (which, atomic, mode, N, v1, exp1, exp1 - v1, v2, exp2, exp2 - v2, len(errors), dt))
    if errors: print("first errors", errors[:3])
    if which != "oracle":
        after = info(c)
        for k in ("atomic_groups", "atomic_commit_windows", "atomic_promotions", "atomic_entries",
                  "atomic_exec_order_holds", "atomic_exec_order_late", "atomic_window_stalls"):
            print("  %s %s -> %s" % (k, before.get(k), after.get(k)))
        print("  stale-cut counter", c.cmd("DEBUG", "ATOMIC-PLAIN-STALE-CUTS"))
    c.close()
finally:
    rc = srv.stop()
    print("server rc", rc)

assert not errors and (v1, v2) == (exp1, exp2), "acknowledged INCR lost"
