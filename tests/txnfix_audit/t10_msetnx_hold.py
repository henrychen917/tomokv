# T10: --atomic 1 cross-shard MSETNX whose group is installed but undecided (DEBUG
# ATOMIC-COMMIT-HOLD 1) while another client SETs one of its keys. Redis: either SET-then-MSETNX
# (MSETNX answers 0, k1 keeps the SET value) or MSETNX-then-SET (MSETNX 1, k1 = SET value).
# Never: MSETNX 1 AND k1 = the MSETNX value with the acknowledged SET gone.
import sys, time
from resp import *
port = int(sys.argv[1]); mode = sys.argv[2] if len(sys.argv) > 2 else "2s"
srv = Server(port, ["--thread-mode", mode, "--atomic", "1", "--enable-debug-command", "yes"], cpus=CPUS)
try:
    c = srv.conn(timeout=30)
    cands = ["n:%d" % i for i in range(400)]
    geo = c.cmd("DEBUG", "SHARDS", *cands)
    owner = {cands[i]: geo[i][1] for i in range(len(cands))}
    k1 = cands[0]; k2 = next(k for k in cands if owner[k] != owner[k1])
    c.cmd("DEL", k1, k2)
    c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 1)
    x = srv.conn(timeout=30); y = srv.conn(timeout=30)
    x.send("MSETNX", k1, "from-msetnx", k2, "from-msetnx")
    time.sleep(0.2)
    t0 = time.time(); ry = y.cmd("SET", k1, "from-set"); ty = time.time() - t0
    c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 0)
    rx = x.read()
    v1 = c.cmd("GET", k1); v2 = c.cmd("GET", k2)
    legal = (rx == 0 and v1 == b"from-set") or (rx == 1 and v1 == b"from-set")
    print("MSETNX=%r SET=%r (%.3fs) -> GET k1=%r GET k2=%r  [%s]" % (rx, ry, ty, v1, v2, "legal" if legal else "NOT SERIALIZABLE: acknowledged SET lost"))
    c.close(); x.close(); y.close()
finally:
    print("server rc", srv.stop())

assert legal, "acknowledged SET lost"
