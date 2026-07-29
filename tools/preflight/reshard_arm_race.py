#!/usr/bin/env python3
"""Reshard ARM/coordinator teardown-window test.

THE DEFECT. The cutover coordinator's teardown published `migration_active = 0` and only THEN
`co_state = CO_IDLE`, with a serverLog() (open/write/close) sitting between the two stores.
`reshardArm` gated on migration_active alone; `reshardBeginCutover` gates on a CAS of
co_state IDLE -> WAIT_CONVERGE. `DEBUG RESHARD START` runs on an IO thread, so an arm could land
inside that window: START succeeded, the following CUTOVER's CAS failed, and the migration was
left ARMED WITH NO COORDINATOR. Nothing in the tree ever starts one afterwards, so
migration_active is stuck at 1 for the life of the process — which

  * refuses every later reshardArm                       => the load balancer is dead, and
  * makes flatResizeCoordinate() return at its own migration_active check => THE FLATSTORE TABLE
    CAN NEVER RESIZE AGAIN. Under a write workload it fills to capacity and flatInsert ends in
    serverPanic("flatstore INSERT: table full") — the server dies.

WHAT THIS TEST DOES. Drives START/CUTOVER as tightly as the protocol allows, so arms keep landing
on the heels of the previous teardown, and then asserts the two things that separate a fixed build
from a broken one:

  1. PROGRESS: cutovers keep completing for the whole run. On a broken build the first arm that
     lands in the window wedges migration_active at 1 and every subsequent START is refused
     forever, so cutovers stop dead and stay stopped.
  2. tomokv_reshard_cutover_no_coord == 0. That counter is incremented at exactly the point where
     an armed migration fails to get a coordinator. It is non-zero on a broken build and
     unreachable on a fixed one.

ANTI-VACUITY. A run that never armed anything would pass (1) trivially, so the test FAILS with
SKIP status if it did not complete at least MIN_CUTOVERS real cutovers. And the acceptance rule
for the fix is not this test passing on its own: it must FAIL on a defect-reintroduced build.

exit 0 = PASS, 1 = FAIL (wedged or counter non-zero), 2 = SKIP (vacuous: too few cutovers)
"""
import socket
import sys
import threading
import time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7899
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 60.0
MIN_CUTOVERS = 200
STOP = threading.Event()


def cmd(*a):
    out = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str):
            x = x.encode()
        out += b"$%d\r\n%s\r\n" % (len(x), x)
    return out


def line(s):
    buf = b""
    while not buf.endswith(b"\r\n"):
        d = s.recv(65536)
        if not d:
            raise EOFError("server closed")
        buf += d
    return buf


def info_counter(s, name):
    """Read INFO stats as a proper RESP bulk string.

    Reading "until the buffer ends with CRLF" does NOT work here: the payload is full of CRLFs, so
    the first recv() satisfies it and the field is usually still in flight — the counter then reads
    as absent and the test fails for the wrong reason on every build. Parse the $<len> header and
    read exactly that many bytes.
    """
    s.sendall(cmd("INFO", "stats"))
    buf = b""
    while b"\r\n" not in buf:
        d = s.recv(1 << 16)
        if not d:
            raise EOFError("server closed")
        buf += d
    head, rest = buf.split(b"\r\n", 1)
    if not head.startswith(b"$"):
        return None
    n = int(head[1:])
    if n < 0:
        return None
    while len(rest) < n + 2:
        d = s.recv(1 << 16)
        if not d:
            raise EOFError("server closed")
        rest += d
    for ln in rest[:n].split(b"\r\n"):
        if ln.startswith(name.encode() + b":"):
            return int(ln.split(b":")[1])
    return None


def warmer(n=8):
    """Keep every event loop — main included — iterating.

    The cutover coordinator advances ONE state per beforeSleep pass on the MAIN thread. On an idle
    server the main loop blocks in epoll until the ~100 ms cron tick, so a migration takes ~6 x
    100 ms and a 60 s run completes far too few cutovers to have raced anything (the test would
    report SKIP for a reason that has nothing to do with the defect). A trickle of PINGs across a
    few connections keeps the loops hot without putting the box under load.
    """
    socks = []
    for _ in range(n):
        try:
            c = socket.create_connection(("127.0.0.1", PORT), timeout=10)
            c.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            socks.append(c)
        except Exception:
            pass
    try:
        while not STOP.is_set():
            for c in socks:
                try:
                    c.sendall(b"PING\r\n")
                    c.recv(64)
                except Exception:
                    return
            time.sleep(0.001)
    finally:
        for c in socks:
            try:
                c.close()
            except Exception:
                pass


def main():
    threading.Thread(target=warmer, daemon=True).start()
    time.sleep(0.2)
    s = socket.create_connection(("127.0.0.1", PORT), timeout=15)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # A boundary-aligned, non-total sub-range of worker 0's range, ping-ponged 0 <-> 1.
    lo, hi, src, dst = 2048, 4096, 0, 1
    cutovers = 0
    refused = 0
    wedge_since = None
    wedged = False
    deadline = time.time() + SECONDS

    while time.time() < deadline:
        s.sendall(cmd("DEBUG", "RESHARD", "START", str(lo), str(hi), str(src), str(dst)))
        if b"+OK" not in line(s):
            refused += 1
            # A refusal is normal while the previous migration is still running. A refusal that
            # NEVER clears is the wedge.
            if wedge_since is None:
                wedge_since = time.time()
            elif time.time() - wedge_since > 10.0:
                wedged = True
                break
            continue
        wedge_since = None
        # shared-kv mode publishes scan_done at arm, so CUTOVER needs no scan wait. (Deliberately
        # no DEBUG RESHARD STATUS polling: STATUS runs migRangeChecksum over the whole shard on
        # this IO thread and would itself stall the very fence under test.)
        s.sendall(cmd("DEBUG", "RESHARD", "CUTOVER"))
        if b"+OK" in line(s):
            cutovers += 1
            src, dst = dst, src

    STOP.set()
    no_coord = info_counter(s, "tomokv_reshard_cutover_no_coord")
    entered = info_counter(s, "tomokv_reshard_arm_refused_coord")

    print("reshard_arm_race: cutovers=%d arm_refusals=%d wedged=%d "
          "cutover_no_coord=%s arm_refused_coord=%s"
          % (cutovers, refused, int(wedged), no_coord, entered))

    if wedged:
        print("FAIL: DEBUG RESHARD START refused for >10s straight after a successful arm — a "
              "migration is armed with no coordinator; migration_active is stuck and flat resizes "
              "are blocked for the life of this process")
        return 1
    if no_coord is None:
        print("FAIL: server does not expose tomokv_reshard_cutover_no_coord (old binary?)")
        return 1
    if no_coord != 0:
        print("FAIL: %d migration(s) were armed with no coordinator" % no_coord)
        return 1
    if cutovers < MIN_CUTOVERS:
        print("SKIP: only %d cutovers completed (< %d) — too few to have raced the teardown "
              "window; this run proves nothing" % (cutovers, MIN_CUTOVERS))
        return 2
    print("PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (EOFError, ConnectionError, OSError) as e:
        # Say WHICH failure this is. A server that vanished mid-test is not the wedge under test
        # (that one stays alive and merely refuses to arm), and grading it as the same thing is how
        # a result gets attributed to the wrong defect.
        print("reshard_arm_race: connection lost: %r" % (e,))
        print("FAIL: server went away during the test (process death, not the arm/coordinator "
              "wedge — check the server log and the wait status)")
        sys.exit(1)
