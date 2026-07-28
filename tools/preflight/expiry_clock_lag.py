#!/usr/bin/env python3
"""Measure the worker clock skew that makes lazy expiry nondeterministic (NIGHT_PLAN B1).

WHAT IS ACTUALLY WRONG (corrected from the original filing). The first write-up said workers "read a
stale clock" because they bypass call()/enterExecutionUnit. Bypass is real -- workers invoke
cmd->proc() directly (server.c CS_LOCAL and the two fake-exec sites), never entering an execution
unit -- but the conclusion that the snapshot is FROZEN is wrong: afterSleep() refreshes
server.cmd_time_snapshot on every main-thread event-loop iteration (server.c:2869). So the clock is
not frozen, it is COARSE and SHARED:

  1. Its cadence is the MAIN thread's loop.  Under worker-dominated load the main thread has little
     to do and mostly sleeps until the cron timer, so the snapshot advances in steps of up to 1/hz
     (100ms at the default hz=10) rather than continuously.
  2. Every worker reads that ONE global, and the main thread rewrites it concurrently -- so the
     value can change UNDERNEATH a command.  That breaks the exact invariant the upstream comment on
     commandTimeSnapshot() exists to protect ("a key can expire only the first time it is accessed
     and not in the middle"), and it is a formal data race on a non-atomic 64-bit global.

WHAT THIS MEASURES. Client-observable expiry lag: SET k PX T, then poll GET k as fast as possible
and record how long past the deadline the key stays readable. With a correct per-command clock the
lag is bounded by scheduling noise (a few ms). With the shared coarse snapshot it quantises toward
the main loop's cadence, and the distribution is what makes repeated identical runs disagree.

Run it while workers are loaded -- an idle server has a busy main loop and hides the defect. The
harness reports p50/p95/max so a fix is judged on the TAIL, not on an average that noise dominates.
"""
import socket, sys, time, threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7897
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 300
TTL_MS = int(sys.argv[3]) if len(sys.argv) > 3 else 60
LOADERS = int(sys.argv[4]) if len(sys.argv) > 4 else 8

stop = threading.Event()


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


def loader(i):
    """Keep the WORKERS busy so the main thread is the idle one -- that is the regime where the
    snapshot's cadence degrades to the cron timer. Without this the probe under-reports."""
    try:
        s = conn()
    except Exception:
        return
    n = 0
    try:
        while not stop.is_set():
            b = b"".join(cmd("SET", "ld:%d:%d" % (i, k), "x" * 64) for k in range(32))
            s.sendall(b + cmd("PING"))
            buf = b""
            while not buf.endswith(b"+PONG\r\n"):
                d = s.recv(65536)
                if not d:
                    return
                buf += d
            n += 32
    except Exception:
        pass


def main():
    try:
        c = conn()
    except Exception as e:
        print("expiry_clock_lag: SKIP (no server): %r" % (e,)); sys.exit(2)

    ts = [threading.Thread(target=loader, args=(i,), daemon=True) for i in range(LOADERS)]
    for t in ts:
        t.start()
    time.sleep(1.0)

    lags = []
    for i in range(SAMPLES):
        k = "ex:%d" % i
        c.sendall(cmd("SET", k, "v", "PX", str(TTL_MS)))
        c.recv(200)
        deadline = time.monotonic() + TTL_MS / 1000.0
        # spin past the deadline until the server admits the key is gone
        while True:
            c.sendall(cmd("GET", k))
            r = c.recv(200)
            now = time.monotonic()
            if r.startswith(b"$-1") or r.startswith(b"_\r\n"):
                lags.append(max(0.0, (now - deadline)) * 1000.0)
                break
            if now - deadline > 5.0:
                lags.append(5000.0)
                break

    stop.set()
    for t in ts:
        t.join(timeout=2)

    lags.sort()
    p50 = lags[len(lags) // 2]
    p95 = lags[int(len(lags) * 0.95)]
    mx = lags[-1]
    print("expiry_clock_lag: n=%d ttl=%dms  p50=%.1fms p95=%.1fms max=%.1fms"
          % (len(lags), TTL_MS, p50, p95, mx))
    # Report only. The pass/fail threshold belongs to the caller, which knows whether it is
    # comparing two builds or gating a release -- baking a number in here would turn measurement
    # noise into a spurious verdict.
    sys.exit(0)


if __name__ == "__main__":
    main()
