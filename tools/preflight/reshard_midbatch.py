#!/usr/bin/env python3
"""Reshard cutover drain-fence probe — the discriminating test for defect H2.

WHAT H2 IS. The cutover fence acked a producer slot after ~2ms of apparent queue emptiness. But
`exQueuePopBatch` publishes the queue head BEFORE the popped batch executes, and `exQueuePush` only
STAGES (the release-store of `tail` happens at the end of `processInputBuffer`), so an empty queue
does not mean an idle producer. The fence then flipped bucket ownership while range commands were
still on their way to — or running on — the OLD owner.

FIRST ATTEMPT AT A REPRO, AND WHY IT WAS WRONG. The obvious shape is "make the worker busy for
hundreds of ms and cut over while it is inside the batch". That reproduces nothing, and the server
log says why: the fence is also gated on the MAIN thread's sentinel, main pushes one every
beforeSleep, and the worker cannot reach that sentinel until it has finished the batch it is
already running. Measured on the unfixed build: DRAINING -> "fence drained" took 121ms against a
135ms batch — the fence was, by accident, waiting the batch out. 12 cutovers x 5 runs: 0 violations.
A busy producer is not the hole, because a busy producer publishes a sentinel within one event-loop
iteration.

THE ACTUAL HOLE is a producer that is STALLED with work destined for the old owner that the
coordinator cannot see. This probe manufactures exactly that, deterministically, from ONE
connection and ONE pipeline:

    LINSERT k BEFORE <tail marker> ... x N     <- staged into the old owner's queue, NOT published
    DEBUG SLEEP <s>                            <- not worker-dispatchable, so it runs INLINE on the
                                                  IO thread, INSIDE processInputBuffer, i.e. before
                                                  the flushExQueues that would publish those pushes
    LLEN k                                     <- parsed only after the sleep returns

While the IO thread sits in that sleep it publishes nothing and pushes no sentinel, so the old
owner's queue from that slot reads EMPTY and is idle-acked; the old owner is genuinely idle, so it
executes main's sentinel at once; the fence completes and the range FLIPS. The IO thread then wakes,
publishes N range writes into the OLD owner's queue, and dispatches the following read under the NEW
table — to the new owner, which serves it immediately.

`LINSERT` returns the list length after inserting, so in program order on one connection `LLEN` must
be >= the last `LINSERT` reply. When the fence is wrong it is smaller by exactly the number of writes
that were still queued at the old owner when ownership moved. That is not a weaker ordering, it is a
result no serial execution can produce.

The probe also reports the server's `tomokv_reshard_fence_midbatch` counter (coordinator ticks that
saw queue-empty-while-a-batch-was-in-flight) and SKIPs rather than passing if no cutover completed,
so a green run cannot come from never entering the window.
"""
import socket, sys, time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7899
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
LIST_LEN = int(sys.argv[3]) if len(sys.argv) > 3 else 2000000
BATCH = int(sys.argv[4]) if len(sys.argv) > 4 else 8
STALL = float(sys.argv[5]) if len(sys.argv) > 5 else 1.2   # DEBUG SLEEP seconds
# Long enough to cover the whole ARM->DRAINING->ack->FLIP chain even at the default hz=10, where
# the coordinator only ticks every 100ms. Rounds whose flip lands AFTER the stall ended are
# reported as window-missed rather than counted as clean, so a short stall degrades to SKIP
# instead of to a false PASS.

LO, HI = 2048, 4096
DEADLINE_FLIP = 90.0      # a correct fence waits out the whole in-flight batch; that is not a hang


def cmd(*a):
    out = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str):
            x = x.encode()
        out += b"$%d\r\n%s\r\n" % (len(x), x)
    return out


class Conn:
    def __init__(self, timeout=180):
        self.s = socket.create_connection(("127.0.0.1", PORT), timeout=timeout)
        self.s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.buf = b""

    def send(self, data):
        self.s.sendall(data)

    def line(self):
        while b"\r\n" not in self.buf:
            d = self.s.recv(65536)
            if not d:
                raise IOError("connection closed by server")
            self.buf += d
        ln, self.buf = self.buf.split(b"\r\n", 1)
        return ln

    def reply(self):
        """Minimal RESP: enough for +status, -err, :int and $bulk."""
        ln = self.line()
        t, rest = ln[:1], ln[1:]
        if t in (b"+", b"-", b":"):
            return (t, rest)
        if t == b"$":
            n = int(rest)
            if n < 0:
                return (t, None)
            while len(self.buf) < n + 2:
                d = self.s.recv(65536)
                if not d:
                    raise IOError("connection closed by server")
                self.buf += d
            v, self.buf = self.buf[:n], self.buf[n + 2:]
            return (t, v)
        raise IOError("unexpected reply type %r" % ln)

    def one(self, *a):
        self.send(cmd(*a))
        return self.reply()

    def close(self):
        try:
            self.s.close()
        except Exception:
            pass


def find(ctrl, key):
    """DEBUG RESHARD FIND is pure-functional (xxh64 + routing table): safe under live load, and it
    is how we see the FLIP itself rather than inferring it."""
    t, v = ctrl.one("DEBUG", "RESHARD", "FIND", key)
    if t != b"+":
        raise IOError("DEBUG RESHARD FIND failed: %r" % v)
    d = dict(p.split(b"=", 1) for p in v.split(b" ") if b"=" in p)
    return int(d[b"bucket"]), int(d[b"routed_ex"])


def info_counter(ctrl, name):
    ctrl.send(cmd("INFO", "stats"))
    t, v = ctrl.reply()
    if t != b"$" or v is None:
        return -1
    for ln in v.split(b"\r\n"):
        if ln.startswith(name.encode() + b":"):
            return int(ln.split(b":", 1)[1])
    return -1


def arm_when_idle(ctrl, src, dst, deadline=30.0):
    """ARM, retrying while a previous migration is still tearing down.

    Deliberately NOT `DEBUG RESHARD STATUS` once the big list exists: STATUS reports a per-shard
    range CHECKSUM, which rdbSaveObject()s every key in the range from the IO thread — one call
    would serialize tens of megabytes of list while the owning worker mutates it. ARM's own
    "migration already active" rejection is the same signal for free."""
    end = time.time() + deadline
    while True:
        t, v = ctrl.one("DEBUG", "RESHARD", "START", str(LO), str(HI), str(src), str(dst))
        if t == b"+":
            return True, v
        if time.time() >= end:
            return False, v
        time.sleep(0.002)


def status(ctrl):
    t, v = ctrl.one("DEBUG", "RESHARD", "STATUS")
    if t != b"+":
        return {}
    return dict(p.split(b"=", 1) for p in v.split(b" ") if b"=" in p)


def place_connections(key):
    """Return (ctrl, probe) placed on threads that make the probe meaningful.

    Two placements silently defeat it, and both are invisible without a check:
      - ctrl on the SAME io thread as probe: the DEBUG SLEEP blocks ctrl's commands too, so the
        cutover is never even triggered inside the window.
      - probe on the MAIN thread: main IS the cutover coordinator, so blocking it stops the state
        machine and no cutover can land during the stall.
    Validate by stalling the probe and requiring (a) ctrl to stay responsive and (b) the coordinator
    to reach DRAINING while the probe sleeps. Run BEFORE the big list exists, so STATUS is cheap.
    """
    for attempt in range(12):
        ctrl, probe = Conn(), Conn()
        probe.send(cmd("DEBUG", "SLEEP", "0.90"))
        time.sleep(0.02)
        t0 = time.time()
        ctrl.one("PING")
        if time.time() - t0 > 0.10:
            probe.reply(); ctrl.close(); probe.close()
            continue                     # ctrl shares the probe's io thread
        _, src = find(ctrl, key)
        dst = 1 if src == 0 else 0
        ok, _ = arm_when_idle(ctrl, src, dst, deadline=5.0)
        drained = False
        if ok and ctrl.one("DEBUG", "RESHARD", "CUTOVER")[0] == b"+":
            end = time.time() + 0.60      # >= 2 coordinator ticks at the default hz=10
            while time.time() < end:
                st = status(ctrl)
                if int(st.get(b"phase", b"0")) >= 2:
                    drained = True       # main is turning => the probe is not on main
                    break
                time.sleep(0.002)
        probe.reply()
        if drained:
            for _ in range(300):         # let that validation cutover finish
                if b"active=0" in (ctrl.one("DEBUG", "RESHARD", "STATUS")[1] or b""):
                    break
                time.sleep(0.01)
            return ctrl, probe
        ctrl.close(); probe.close()
        time.sleep(0.05)
    return None, None


def main():
    boot = Conn()
    key = None
    for i in range(4000):
        k = "mb:%d" % i
        b, _ = find(boot, k)
        if LO <= b < HI:
            key = k
            break
    boot.close()
    if key is None:
        print("reshard_midbatch: SKIP (no key found in bucket range [%d,%d))" % (LO, HI))
        sys.exit(2)

    ctrl, probe = place_connections(key)
    if ctrl is None:
        print("reshard_midbatch: SKIP (could not place ctrl/probe on usable io threads)")
        sys.exit(2)

    # The list the LINSERT scan walks. The tail marker is the pivot, so every LINSERT is a full
    # traversal — that is what keeps the OLD owner busy long after the flip has landed.
    ctrl.one("DEL", key)
    pushed = 0
    while pushed < LIST_LEN:
        n = min(2000, LIST_LEN - pushed)
        ctrl.send(cmd("RPUSH", key, *["v%d" % (pushed + j) for j in range(n)]))
        ctrl.reply()
        pushed += n
    ctrl.one("RPUSH", key, "TAILMARK")

    t0 = time.time()
    ctrl.one("LINSERT", key, "BEFORE", "TAILMARK", "warm")
    per_op = time.time() - t0
    print("reshard_midbatch: key=%s list=%d one LINSERT=%.1f ms -> batch of %d ~= %.0f ms, stall=%.2fs"
          % (key, LIST_LEN, per_op * 1000, BATCH, per_op * BATCH * 1000, STALL), flush=True)
    if per_op * BATCH < 0.050:
        print("reshard_midbatch: SKIP (batch only %.0f ms; the old owner would finish before the "
              "read lands - raise LIST_LEN)" % (per_op * BATCH * 1000))
        sys.exit(2)

    mid0 = info_counter(ctrl, "tomokv_reshard_fence_midbatch")
    viol = 0
    early = 0
    rounds_run = 0
    cutovers = 0
    worst = 0
    for r in range(ROUNDS):
        _, src = find(ctrl, key)
        dst = 1 if src == 0 else 0
        if src not in (0, 1):
            print("  round %d: range drifted to worker %d; stopping" % (r, src), flush=True)
            break

        # ARM first: arming can block for as long as the PREVIOUS cutover takes to tear down, and
        # that wait would otherwise burn the stall this round depends on. COPYING is inert under
        # shared node dbs (no scan, no capture), so sitting in it costs nothing.
        ok, v = arm_when_idle(ctrl, src, dst)
        if not ok:
            print("  round %d: ARM rejected (%r)" % (r, v), flush=True)
            continue

        # ONE pipeline, ONE connection: N staged range writes, an inline stall, then the read.
        t_send = time.time()
        probe.send(b"".join(cmd("LINSERT", key, "BEFORE", "TAILMARK", "x%d.%d" % (r, j))
                            for j in range(BATCH))
                   + cmd("DEBUG", "SLEEP", "%.3f" % STALL)
                   + cmd("LLEN", key))
        time.sleep(0.02)                    # the io thread is now inside DEBUG SLEEP

        t, v = ctrl.one("DEBUG", "RESHARD", "CUTOVER")
        if t != b"+":
            print("  round %d: CUTOVER rejected (%r)" % (r, v), flush=True)
            for _ in range(BATCH + 2):
                probe.reply()
            continue

        end = time.time() + DEADLINE_FLIP
        flipped = False
        while time.time() < end:
            if find(ctrl, key)[1] == dst:
                flipped = True
                break
            time.sleep(0.001)
        if not flipped:
            print("  round %d: FLIP never landed within %.0fs (fence hang?)" % (r, DEADLINE_FLIP),
                  flush=True)
            for _ in range(BATCH + 2):
                probe.reply()
            continue
        cutovers += 1
        flip_dt = time.time() - t_send

        lens = []
        for _ in range(BATCH):
            t, v = probe.reply()
            lens.append(int(v) if t == b":" else -1)
        probe.reply()                        # DEBUG SLEEP's +OK
        t, v = probe.reply()
        llen = int(v) if t == b":" else -1

        rounds_run += 1

        # SIGNAL 1 (the fence's own contract, measured black-box). The producer is provably still
        # stalled until DEBUG SLEEP returns, and it had already sent BATCH range writes bound for
        # the old owner. An ownership flip observed before the stall ends therefore means the fence
        # acked a producer with un-retired range work — the defect itself, independent of whether
        # the client-visible consequence below happens to materialise this round.
        if flip_dt <= STALL:
            early += 1
            print("  EARLY FLIP round %d: ownership moved %d->%d %.0f ms into a %.0f ms producer "
                  "stall, with %d range writes still queued for %d"
                  % (r, src, dst, flip_dt * 1000, STALL * 1000, BATCH, src), flush=True)

        # SIGNAL 2 (the client-visible consequence): same connection, program order.
        last = max(lens)
        if llen < last:
            viol += 1
            worst = max(worst, last - llen)
            print("  VIOLATION round %d: LLEN=%d < last LINSERT reply=%d (%d writes issued earlier "
                  "on this connection were still queued at worker %d when ownership moved to %d)"
                  % (r, llen, last, last - llen, src, dst), flush=True)

    mid1 = info_counter(ctrl, "tomokv_reshard_fence_midbatch")
    aborts = info_counter(ctrl, "tomokv_reshard_fence_aborts")
    print("reshard_midbatch: violations=%d early_flips=%d /%d cutovers=%d worst_gap=%d "
          "fence_midbatch_ticks=%d fence_aborts=%d"
          % (viol, early, rounds_run, cutovers, worst, mid1 - mid0, aborts), flush=True)
    ctrl.one("DEL", key)
    ctrl.close()
    probe.close()

    if cutovers < 3:
        print("reshard_midbatch: SKIP (only %d cutover(s); the window was barely entered)" % cutovers)
        sys.exit(2)
    sys.exit(1 if (viol or early) else 0)


if __name__ == "__main__":
    main()
