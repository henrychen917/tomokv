# T03: atomic-ON cross-shard movers replay phase-one images. While the mover's group is installed
# but undecided (DEBUG ATOMIC-COMMIT-HOLD 1 keeps the completed group in the commit queue), a plain
# write to the destination clones the pre-group value; at commit the mover's stale image wins.
# Redis: the concurrent write always survives. Variants: SMOVE, LMOVE, PFMERGE. Control: atomic 0.
# Usage: t03_mover_replay.py <port> <atomic 0|1> <mode 2s|1s>
import sys, time, select
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
        deadline = time.monotonic() + 5
        while int(info(c).get("atomic_pending_entries", 0)):
            assert time.monotonic() < deadline, "setup candidates did not drain before arming"
            time.sleep(.001)
        before = info(c)
        g0 = int(before.get("atomic_groups", 0))
        c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 1)
        x = srv.conn(timeout=30); y = srv.conn(timeout=30)
        x.send(*mover)
        if atomic == "1":
            deadline = time.monotonic() + 5
            while int(info(c).get("atomic_pending_entries", 0)) == 0:
                assert time.monotonic() < deadline, "mover installed no held candidate"
                time.sleep(.001)
            assert not select.select([x.s], [], [], 0)[0], "mover hold never opened"
        else:
            rx = x.read()  # explicit non-held atomic-0 companion
        t0 = time.time(); y.send(*concurrent)
        deadline = time.monotonic() + 5
        while not select.select([y.s], [], [], 0)[0]:
            if int(info(c).get("atomic_txn_writer_waits", 0)) > int(before.get("atomic_txn_writer_waits", 0)):
                break
            assert time.monotonic() < deadline, "writer neither replied nor reached held claim"
            time.sleep(.001)
        print("witness", name, "held candidate" if atomic == "1" else "atomic-0 non-held control", flush=True)
        c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 0)
        if atomic == "1": rx = x.read()
        ry = y.read(); ty = time.time() - t0
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
