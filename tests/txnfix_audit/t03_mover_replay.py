# T03: atomic-ON cross-shard movers replay phase-one images. While the mover's group is installed
# but undecided (DEBUG ATOMIC-COMMIT-HOLD 1 keeps the completed group in the commit queue), a plain
# write to the destination clones the pre-group value; at commit the mover's stale image wins.
# Redis: the concurrent write always survives. Variants: SMOVE, LMOVE, PFMERGE. Control: atomic 0.
# Usage: t03_mover_replay.py <port> <atomic 0|1> <mode 2s|1s>
import sys, time
from resp import *
port = int(sys.argv[1]); atomic = sys.argv[2]; mode = sys.argv[3]
srv = Server(port, ["--thread-mode", mode, "--atomic", atomic, "--enable-debug-command", "yes"],
             cpus=CPUS)
try:
    c = srv.conn(timeout=30)
    cands = ["m:%d" % i for i in range(400)]
    geo = c.cmd("DEBUG", "SHARDS", *cands)
    owner = {cands[i]: geo[i][1] for i in range(len(cands))}
    src = cands[0]; dst = next(k for k in cands if owner[k] != owner[src])
    print("geometry src=%s ex%d dst=%s ex%d" % (src, owner[src], dst, owner[dst]))
    cases = [
        ("SMOVE", [["DEL", src, dst], ["SADD", src, "m"], ["SADD", dst, "a"]],
         ["SMOVE", src, dst, "m"], ["SADD", dst, "z"], ["SMEMBERS", dst],
         lambda v: sorted(x.decode() for x in v), ["a", "m", "z"]),
        ("LMOVE", [["DEL", src, dst], ["RPUSH", src, "m"], ["RPUSH", dst, "a"]],
         ["LMOVE", src, dst, "LEFT", "RIGHT"], ["RPUSH", dst, "z"], ["LRANGE", dst, 0, -1],
         lambda v: sorted(x.decode() for x in v), ["a", "m", "z"]),
        ("PFMERGE", [["DEL", src, dst], ["PFADD", src, "s1", "s2"], ["PFADD", dst, "a"]],
         ["PFMERGE", dst, src], ["PFADD", dst, "z1", "z2", "z3"], ["PFCOUNT", dst],
         lambda v: v, 6),
    ]
    failures = []
    for name, setup, mover, concurrent, check, norm, expected in cases:
        for cmd in setup: c.cmd(*cmd)
        g0 = int(info(c).get("atomic_groups", 0))
        c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 1)
        x = srv.conn(timeout=30); y = srv.conn(timeout=30)
        x.send(*mover)
        time.sleep(0.2)
        t0 = time.time(); ry = y.cmd(*concurrent); ty = time.time() - t0
        c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 0)
        rx = x.read()
        got = norm(c.cmd(*check))
        g1 = int(info(c).get("atomic_groups", 0))
        verdict = "OK" if got == expected else "LOST WRITE"
        if got != expected: failures.append((name, got, expected))
        print("%-8s atomic=%s mode=%s mover=%r concurrent=%r (%.3fs) -> %s=%r expected %r  [%s] groups+%d"
              % (name, atomic, mode, rx, ry, ty, check[0], got, expected, verdict, g1 - g0))
        x.close(); y.close()
    c.close()
finally:
    print("server rc", srv.stop())

assert not failures, failures
