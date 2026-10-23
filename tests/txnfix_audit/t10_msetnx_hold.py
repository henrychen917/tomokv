# T10: --atomic 1 cross-shard MSETNX whose group is installed but undecided (DEBUG
# ATOMIC-COMMIT-HOLD 1) while another client SETs one of its keys. Redis: either SET-then-MSETNX
# (MSETNX answers 0, k1 keeps the SET value) or MSETNX-then-SET (MSETNX 1, k1 = SET value).
# Never: MSETNX 1 AND k1 = the MSETNX value with the acknowledged SET gone.
import sys, time, select
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
    deadline = time.monotonic() + 5
    while int(info(c, "stats")["atomic_pending_entries"]):
        assert time.monotonic() < deadline, "setup records did not drain before arming"
        time.sleep(.001)
    c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 1)
    x = srv.conn(timeout=30); y = srv.conn(timeout=30)
    before = info(c, "stats")
    x.send("MSETNX", k1, "from-msetnx", k2, "from-msetnx")
    tracking = c.cmd("CONFIG", "GET", "atomic")[1] != b"0"
    deadline = time.monotonic() + 5
    while tracking and int(info(c, "stats")["atomic_pending_entries"]) <= int(before["atomic_pending_entries"]):
        assert time.monotonic() < deadline, "held MSETNX never installed a candidate"
        time.sleep(.001)
    if tracking:
        assert not select.select([x.s], [], [], 0)[0], "MSETNX replied before held decision was released"
    else:
        # Atomic-0 is the historical non-held companion: there is no admitted
        # group to hold. Join MSETNX before SET and retain the same data oracle.
        rx = x.read()
        print("atomic-0 companion: no group hold is possible", flush=True)
    t0 = time.time(); y.send("SET", k1, "from-set")
    if tracking and "atomic_txn_writer_waits" in before:
        deadline = time.monotonic() + 5
        while int(info(c, "stats")["atomic_txn_writer_waits"]) <= int(before["atomic_txn_writer_waits"]):
            assert time.monotonic() < deadline, "plain writer did not reach the held claim"
            time.sleep(.001)
        assert not select.select([y.s], [], [], 0)[0], "plain writer passed the held validation"
    if tracking:
        print("held-window witness: candidate installed, decision held, SET submitted", flush=True)
    c.cmd("DEBUG", "ATOMIC-COMMIT-HOLD", 0)
    if tracking: rx = x.read()
    ry = y.read(); ty = time.time() - t0
    v1 = c.cmd("GET", k1); v2 = c.cmd("GET", k2)
    legal = (rx == 0 and v1 == b"from-set") or (rx == 1 and v1 == b"from-set")
    print("MSETNX=%r SET=%r (%.3fs) -> GET k1=%r GET k2=%r  [%s]" % (rx, ry, ty, v1, v2, "legal" if legal else "NOT SERIALIZABLE: acknowledged SET lost"))
    c.close(); x.close(); y.close()
finally:
    print("server rc", srv.stop())

assert legal, "acknowledged SET lost"
