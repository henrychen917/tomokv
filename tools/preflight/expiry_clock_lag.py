#!/usr/bin/env python3
"""Measure client-observed lazy-expiry lag on the worker path (F-clock + the guard race).

Usage: expiry_clock_lag.py [port] [samples] [ttl_ms] [loaders] [poll_ms] [no_active]

TWO DEFECTS LIVE HERE, AND THEY NEED OPPOSITE REGIMES TO SEE. Both come from the same root: a
worker thread runs cmd->proc() directly (server.c exExecFake, and csSubExec for scatter subs) and
so never passes through call()/enterExecutionUnit(), where a command normally latches its
execution-unit state. Everything call() would have given it therefore has to come from a global —
and a global shared by N workers is either stale or raced.

  D1. THE GUARD RACE (found 2026-07-28, fixed).  moduleNotifyKeyUnlink() raises
      server.allow_access_expired / .allow_access_trimmed around its callbacks and lowers them
      after. It runs on EVERY key overwrite and EVERY delete (db.c setKey / dbGenericDelete), i.e.
      on every worker's hot path, and those were plain non-atomic ints. Concurrent ++/-- lose
      updates, the counter walks off zero and stays there, and keyIsExpired() then returns "not
      expired" forever: lazy expiry is dead process-wide. Needs WRITE TRAFFIC to show, so run it
      with loaders > 0 and poll fast. On the unfixed build the counter reached +7227 in ~4s with 4
      workers and 8 loaders, and a `SET k v PX 60` key was still readable 25 seconds later.

  D2. THE COARSE/SHARED CLOCK (F-clock).  With D1 fixed, expiry works, but a worker still reads
      the single global server.cmd_time_snapshot, which is rewritten only by the MAIN thread's
      loop (afterSleep, and call()'s enterExecutionUnit). Note this is the opposite regime from
      D1: the busier the server, the more often that loop turns and the FRESHER the clock. The
      defect shows at LOW command rate, where the main loop falls back to the cron timer and the
      snapshot advances in steps of up to 1/hz (100ms at the default hz=10). So run D2 with
      loaders = 0 and a poll gap of a few ms; polling flat out would keep the loop hot and hide it.

      Do NOT "fix" D2 by latching server.mstime. afterSleepIO() looks like it refreshes mstime per
      IO-thread loop iteration, but aeProcessEventsIO() never calls eventLoop->aftersleep (only
      the generic aeProcessEvents(), which only the main loop runs, does — ae.c:426). mstime is
      therefore refreshed by the main thread and nothing else, and measures exactly as stale as
      cmd_time_snapshot (verified side by side: both p50 77ms / max 84ms in the D2 regime).

TURN THE ACTIVE CYCLE OFF FOR D2 (no_active=1, needs `--enable-debug-command local`). Both defects
are on the LAZY path, but the active expire cycle is a second, independent way a key can vanish —
and it does NOT read commandTimeSnapshot(), it takes a fresh `ustime()` of its own (expire.c). Its
fast pass runs from beforeSleep, so on a nearly idle server with a nearly empty keyspace it finds
and deletes the probe's key within about a millisecond and reports a healthy number no matter how
broken the lazy clock is. That is exactly how a build with lazy expiry entirely dead still scored
p50=1.0ms in this regime. Measuring D2 without disabling it does not measure D2.

WHAT IS REPORTED. Per sample: SET k v PX <ttl>, then poll GET until the server admits the key is
gone, and record how far past the deadline that happened. p50/p95/max, because a fix is judged on
the TAIL — a mean is dominated by scheduling noise. `never` counts samples that were still
readable when the 5s cutoff hit; on a build with D1 present that is every sample. `early` counts
samples whose key was NOT readable before its own deadline — any nonzero value means the cell
measured nothing and its p50/p95 are meaningless, not good.

No pass/fail threshold is baked in: the caller knows whether it is comparing two builds or gating
a release, and a hardcoded number here would turn measurement noise into a verdict.
"""
import socket, sys, time, threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7897
SAMPLES = int(sys.argv[2]) if len(sys.argv) > 2 else 300
TTL_MS = int(sys.argv[3]) if len(sys.argv) > 3 else 60
LOADERS = int(sys.argv[4]) if len(sys.argv) > 4 else 8
POLL_MS = float(sys.argv[5]) if len(sys.argv) > 5 else 0.0
NO_ACTIVE = int(sys.argv[6]) if len(sys.argv) > 6 else 0

CUTOFF_S = 5.0
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
    """Write traffic. Two jobs: keep the workers executing, and — because these SETs OVERWRITE
    existing keys — drive moduleNotifyKeyUnlink(), which is what exercises D1's guard counter."""
    try:
        s = conn()
    except Exception:
        return
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
    except Exception:
        pass


def main():
    try:
        c = conn()
    except Exception as e:
        print("expiry_clock_lag: SKIP (no server): %r" % (e,)); sys.exit(2)

    active = "on"
    if NO_ACTIVE:
        # Report what actually happened: a silently-refused DEBUG would turn this cell back into
        # the vacuous version it exists to replace.
        c.sendall(cmd("DEBUG", "SET-ACTIVE-EXPIRE", "0"))
        active = "off" if c.recv(200).startswith(b"+OK") else "REFUSED"

    ts = [threading.Thread(target=loader, args=(i,), daemon=True) for i in range(LOADERS)]
    for t in ts:
        t.start()
    if LOADERS:
        time.sleep(1.0)

    lags = []
    never = 0
    early = 0
    for i in range(SAMPLES):
        k = "ex:%d" % i
        c.sendall(cmd("SET", k, "v", "PX", str(TTL_MS)))
        c.recv(200)
        deadline = time.monotonic() + TTL_MS / 1000.0
        # ANTI-VACUOUS GUARD. Every number below is "how long past the deadline the key stayed
        # readable", which is trivially ~0 if the key was never readable in the first place — a
        # rejected SET, a desynced reply stream, or a key routed to a shard the GET does not read
        # would all score a perfect result while measuring nothing. So prove the key IS live
        # before the deadline. early>0 invalidates the cell; it is not a tuning knob.
        c.sendall(cmd("GET", k))
        if not c.recv(200).startswith(b"$1"):
            early += 1
        while True:
            if POLL_MS:
                time.sleep(POLL_MS / 1000.0)
            c.sendall(cmd("GET", k))
            r = c.recv(200)
            now = time.monotonic()
            if r.startswith(b"$-1") or r.startswith(b"_\r\n"):
                lags.append(max(0.0, (now - deadline)) * 1000.0)
                break
            if now - deadline > CUTOFF_S:
                lags.append(CUTOFF_S * 1000.0)
                never += 1
                break

    stop.set()
    for t in ts:
        t.join(timeout=2)

    lags.sort()
    p50 = lags[len(lags) // 2]
    p95 = lags[int(len(lags) * 0.95)]
    mx = lags[-1]
    print("expiry_clock_lag: n=%d ttl=%dms loaders=%d poll=%.1fms active=%s  "
          "p50=%.1fms p95=%.1fms max=%.1fms never=%d early=%d%s"
          % (len(lags), TTL_MS, LOADERS, POLL_MS, active, p50, p95, mx, never, early,
             "  *** CELL INVALID: key was not live before its deadline ***" if early else ""))
    sys.exit(0)


if __name__ == "__main__":
    main()
