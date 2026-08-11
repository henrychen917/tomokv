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
     forever, so cutovers stop dead and stay stopped. NOTE the check ORDER in main() is
     load-bearing: `wedged` and `no_coord != 0` are both evaluated BEFORE the MIN_CUTOVERS check,
     because a build that wedges early never reaches MIN_CUTOVERS and must report FAIL, not SKIP.
  2. tomokv_reshard_cutover_no_coord == 0. That counter is incremented at exactly the point where
     an armed migration fails to get a coordinator. It is non-zero on a broken build and
     unreachable on a fixed one. It is the PRIMARY assertion — checked before `wedged`, which is
     the coarser symptom and can misname its own cause (see the comment in main()).

A COUNTER IS ONLY AN ASSERTION IF IT CAN COUNT. Until 2026-07-29 this test passed on every build,
defective or not, including one with the teardown window artificially widened to 200 us: `mig_arm_seq`
was declared and never incremented, so reshardBeginCutover's "is the running coordinator servicing
MY arm" latch (`co_serving_arm == mig_arm_seq`, 0 == 0) was true for every caller, the CAS-failure
path returned +OK instead of counting, and cutover_no_coord could never leave 0. Both this test's
assertions were dead. If this test ever again passes on a build you believe is broken, check that
the counter is REACHABLE before you conclude the defect is absent.

ANTI-VACUITY. A run that never armed anything would pass (1) trivially, so the test FAILS with
SKIP status if it did not complete at least MIN_CUTOVERS real cutovers. And the acceptance rule
for the fix is not this test passing on its own: it must FAIL on a defect-reintroduced build.

exit 0 = PASS, 1 = FAIL (wedged or counter non-zero), 2 = SKIP (vacuous: too few
cutovers), 4 = DIED (the server went away mid-run: a different failure, never graded as the wedge)
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


class Reader:
    """Buffered line reader.

    Required because this probe PIPELINES. A "read until the buffer ends with CRLF" helper returns
    BOTH replies when they arrive in one segment, and the next call then blocks forever waiting for
    a reply that was already consumed — the loop stalls on the socket timeout and the run reports
    nothing useful. Keep the residue.
    """

    def __init__(self, sock):
        self.s = sock
        self.buf = b""

    def line(self):
        while b"\r\n" not in self.buf:
            d = self.s.recv(1 << 16)
            if not d:
                raise EOFError("server closed")
            self.buf += d
        ln, self.buf = self.buf.split(b"\r\n", 1)
        return ln

    def bulk(self):
        """Read one RESP bulk string ($<len>\\r\\n<payload>\\r\\n) and return the payload."""
        head = self.line()
        if not head.startswith(b"$"):
            return None
        n = int(head[1:])
        if n < 0:
            return None
        while len(self.buf) < n + 2:
            d = self.s.recv(1 << 16)
            if not d:
                raise EOFError("server closed")
            self.buf += d
        payload, self.buf = self.buf[:n], self.buf[n + 2:]
        return payload


def info_counter(r, name):
    """Read one counter out of INFO stats.

    Note this goes through Reader.bulk(): the payload is full of CRLFs, so any "read until the
    buffer ends with CRLF" shortcut is satisfied by the first recv() and the field is usually still
    in flight — the counter then reads as absent and the test fails for the wrong reason on EVERY
    build, fixed and broken alike.
    """
    r.s.sendall(cmd("INFO", "stats"))
    payload = r.bulk()
    if payload is None:
        return None
    for ln in payload.split(b"\r\n"):
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
    r = Reader(s)

    # A boundary-aligned, non-total sub-range of worker 0's range, ping-ponged 0 <-> 1.
    lo, hi, src, dst = 2048, 4096, 0, 1
    cutovers = 0
    refused = 0
    wedge_since = None
    wedged = False
    deadline = time.time() + SECONDS

    while time.time() < deadline:
        # START and CUTOVER go out as ONE pipelined write, deliberately.
        #
        # The window under test is the gap between the teardown's `migration_active = 0` and its
        # `co_state = CO_IDLE` — tens of microseconds (a serverLog open/write/close, plus whatever
        # the scheduler adds). The defect needs BOTH commands inside it: the arm must see
        # active == 0, and the cutover must still find co_state != IDLE. Issued as two round trips
        # they are ~50-100 us apart — reliably WIDER than the window, so a request/response probe
        # would report a clean PASS on a build that still has the defect. Pipelined, they are
        # executed back-to-back on the same IO thread, microseconds apart.
        #
        # (Deliberately no DEBUG RESHARD STATUS anywhere: it is an extra round trip inside the
        # window under test. The stronger reason this comment used to give -- "STATUS runs
        # migRangeChecksum over the whole shard on this IO thread" -- died with the copy engine on
        # 2026-07-28: STATUS now only formats six scalars. The scan_done wait it also mentions is
        # gone for the same reason; ARM goes straight to COPYING, so CUTOVER needs no wait.)
        s.sendall(cmd("DEBUG", "RESHARD", "START", str(lo), str(hi), str(src), str(dst))
                  + cmd("DEBUG", "RESHARD", "CUTOVER"))
        armed_ok = r.line().startswith(b"+OK")
        cut_ok = r.line().startswith(b"+OK")
        if not armed_ok:
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
        if cut_ok:
            cutovers += 1
            src, dst = dst, src

    STOP.set()
    no_coord = info_counter(r, "tomokv_reshard_cutover_no_coord")

    print("reshard_arm_race: cutovers=%d arm_refusals=%d wedged=%d cutover_no_coord=%s"
          % (cutovers, refused, int(wedged), no_coord))

    # THE COUNTER IS CHECKED FIRST, and that ordering is a correction, not a preference. Measured
    # 2026-07-29 on a defect-reintroduced build: the run reported BOTH wedged=1 and
    # cutover_no_coord=1, and the wedge message ("migration_active is stuck for the life of this
    # process") was WRONG about its own mechanism — the server log showed the orphaned migration
    # was adopted by the NEXT pipelined CUTOVER and completed. What actually stopped the run was
    # this probe's own bookkeeping: an orphaned arm replies -ERR to its CUTOVER, so `src, dst` are
    # not swapped, while the migration completes anyway and moves the buckets — every later START
    # then fails reshardRangeValid and is refused forever. Both symptoms are downstream of the same
    # defect, so the verdict was right either way, but only cutover_no_coord names it exactly.
    if no_coord is None:
        print("FAIL: server does not expose tomokv_reshard_cutover_no_coord (old binary?)")
        return 1
    if no_coord != 0:
        print("FAIL: %d migration(s) were ARMED WITH NO COORDINATOR — an arm landed inside the "
              "cutover teardown window and its CUTOVER's CAS lost to the outgoing coordinator "
              "(docs/BUGS.md A10)" % no_coord)
        return 1
    if wedged:
        print("FAIL: DEBUG RESHARD START refused for >10s straight after a successful arm. "
              "cutover_no_coord is 0, so this is NOT the A10 orphan: either migration_active is "
              "genuinely stuck, or the armable range moved out from under this probe — read "
              "server.log before attributing it")
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
        print("DIED: server went away during the test (process death, not the arm/coordinator "
              "wedge — check the server log and the wait status)")
        # Exit 4, NOT 1. The validate script counts a 1 from the pre-fix arm as "the discriminating
        # test caught the defect"; a server that was killed out from under the run must not be
        # allowed to masquerade as that, or the fix would be accepted on evidence it never produced.
        sys.exit(4)
