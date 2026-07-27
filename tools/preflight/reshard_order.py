#!/usr/bin/env python3
"""Reshard ordering probe — the coverage preflight never had.

`grep -rn RESHARD tools/preflight/` returned NOTHING before this file existed, which is how the
cutover fence accumulated three fail-open holes without a single test noticing.

WHAT IT PROBES (task #48, "hole 3"): migHoldIfDraining used to gate on CMD_WRITE only, so during
the DRAINING window READS kept routing to the OLD owner A while the same client's next command
routed to the NEW owner C after the flip. A same-client read/write pair then executes on two
different workers with nothing ordering them.

THE SHAPE, per connection, all on ONE connection so program order is defined:

    GET  k      -> must observe the value BEFORE the SET below
    SET  k NEW
    GET  k      -> must observe NEW

A violation is the first GET returning NEW: a read issued BEFORE the write observed the write.
That is not a weaker ordering, it is a result no serial execution can produce.

We drive a reshard of k's bucket concurrently so the window is actually exercised. Without the
reshard running this probe is vacuous by construction, so the harness ASSERTS that at least one
cutover completed; if none did, it reports SKIP rather than PASS. (This project has shipped six
mechanisms whose acceptance check could not fail; a green run that never entered the window would
be the seventh.)
"""
import socket, sys, time, threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7899
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
NKEYS = 64


def cmd(*a):
    out = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str):
            x = x.encode()
        out += b"$%d\r\n%s\r\n" % (len(x), x)
    return out


def conn():
    s = socket.create_connection(("127.0.0.1", PORT), timeout=10)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def readn(s, nlines):
    buf = b""
    while buf.count(b"\r\n") < nlines:
        d = s.recv(65536)
        if not d:
            break
        buf += d
    return buf


stop = threading.Event()
cutovers = [0]
arm_errs = [0]


def resharder():
    """Drive real cutovers so the DRAINING window is genuinely entered."""
    try:
        s = conn()
    except Exception:
        return
    # The range must be a NON-TOTAL, boundary-aligned sub-range of src's contiguous range, and
    # dst must be src+-1. [0,4096) is worker 0's ENTIRE range at io4/ex4 and is refused; a partial
    # range at the shared boundary is accepted and can be ping-ponged 0<->1 indefinitely.
    lo, hi = 2048, 4096
    src, dst = 0, 1
    while not stop.is_set():
        # A migration must fully finish (active=0) before the next can arm -- otherwise every
        # subsequent ARM is refused with "migration already active" and the probe silently degrades
        # to ~1 cutover for the whole run, which is far too thin to catch a rare interleaving.
        for _ in range(400):
            s.sendall(cmd("DEBUG", "RESHARD", "STATUS"))
            if b"active=0" in readn(s, 1):
                break
            time.sleep(0.005)
        if stop.is_set():
            break
        # alternate direction so the range ping-pongs between two workers
        s.sendall(cmd("DEBUG", "RESHARD", "START", str(lo), str(hi), str(src), str(dst)))
        r = readn(s, 1)
        if b"+OK" in r:
            # wait for the cold scan, then cut over
            for _ in range(200):
                s.sendall(cmd("DEBUG", "RESHARD", "STATUS"))
                st = readn(s, 1)
                if b"scan_done=1" in st:
                    break
                time.sleep(0.005)
            s.sendall(cmd("DEBUG", "RESHARD", "CUTOVER"))
            if b"+OK" in readn(s, 1):
                cutovers[0] += 1
            src, dst = dst, src
        else:
            arm_errs[0] += 1
        time.sleep(0.002)
    try:
        s.close()
    except Exception:
        pass


def main():
    s = conn()
    # seed
    for i in range(NKEYS):
        s.sendall(cmd("SET", "rs:%d" % i, "OLD"))
    readn(s, NKEYS)

    t = threading.Thread(target=resharder, daemon=True)
    t.start()
    time.sleep(0.3)

    viol = 0
    checked = 0
    # Run until we have observed MIN_CUTOVERS real cutovers (or hit the time cap). A fixed round
    # count is the wrong budget: 3000 GET/SET rounds complete faster than one migration cycle, so
    # the probe was finishing after a single cutover -- far too thin to catch a rare interleaving.
    MIN_CUTOVERS = 6
    DEADLINE = time.time() + 180
    r = -1
    while (cutovers[0] < MIN_CUTOVERS or checked < ROUNDS) and time.time() < DEADLINE:
        r += 1
        k = "rs:%d" % (r % NKEYS)
        s.sendall(cmd("SET", k, "OLD"))
        readn(s, 1)
        # one pipeline, program order defined: read, write, read
        # Alternate single-key GET and multi-key MGET so BOTH hold paths are exercised:
        # migHoldIfDraining (single key, processCommand) and migHoldKeyIfDraining (coalesced
        # cross-shard, csBuildCoalescedSubs -- reachable from the drain thread, so if widening
        # that hold to reads could hang a cutover, this is where it shows up).
        if r % 2:
            s.sendall(cmd("GET", k) + cmd("SET", k, "NEW") + cmd("GET", k))
            buf = readn(s, 3)
        else:
            k2 = "rs:%d" % ((r + 7) % NKEYS)
            k3 = "rs:%d" % ((r + 19) % NKEYS)
            s.sendall(cmd("MGET", k, k2, k3) + cmd("SET", k, "NEW") + cmd("GET", k))
            buf = readn(s, 5)
        parts = buf.split(b"\r\n")
        pre = None
        for i, p in enumerate(parts):
            if p.startswith(b"$") and i + 1 < len(parts):
                pre = parts[i + 1]
                break
        checked += 1
        if pre == b"NEW":
            viol += 1
            if viol <= 3:
                print("  VIOLATION round %d: read-before-write observed NEW" % r, flush=True)

    stop.set()
    t.join(timeout=3)
    print("reshard_order: violations=%d/%d cutovers=%d arm_rejects=%d"
          % (viol, checked, cutovers[0], arm_errs[0]))
    if cutovers[0] < 3:
        # too few cutovers -> the window was barely entered, so a clean result proves little
        print("reshard_order: SKIP (only %d cutover(s); too thin to be evidence)" % cutovers[0])
        sys.exit(2)
    sys.exit(1 if viol else 0)


if __name__ == "__main__":
    main()
