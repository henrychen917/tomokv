#!/usr/bin/env python3
"""Reshard hot-skew HANG probe.

Regime: a SUSTAINED hot-key skew (a handful of keys, every connection hitting them) while
cutovers of the range holding those keys run back to back. That is the regime in which the
server was reported to stop answering after ~8 migrations.

What this does, and why each part exists:

  * load        - N connections, pipelined, all hammering the same K keys (default 16), a
                  read/write mix. The keys are chosen AFTER asking the server which bucket
                  each candidate hashes to, so every hot key is guaranteed to sit inside the
                  range we then migrate. A random 16-key set spreads over 4 shards and never
                  puts real DRAINING pressure on the moving range.
  * resharder   - drives real cutovers (DEBUG RESHARD START/CUTOVER), ping-ponging the range
                  between two adjacent workers, or (with --auto) leaves it to the balancer.
  * watchdog    - a SEPARATE connection that PINGs on a deadline, plus a FRESH connect+PING
                  each round. Those two distinguish "listener dead / connect refused" from
                  "connects fine, never replies" from "everything fine".

On a stall it writes a marker line and exits non-zero so the caller can grab stacks BEFORE
anything is killed. It never kills the server itself.

Exit codes: 0 = no stall, 3 = stall detected, 2 = setup failure / no cutovers (vacuous run).
"""
import argparse
import os
import socket
import sys
import threading
import time

STOP = threading.Event()
STALL = []          # (kind, detail, t)
CUTOVERS = [0]
ARM_ERRS = [0]
OPS = [0]


def cmd(*a):
    out = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str):
            x = x.encode()
        out += b"$%d\r\n%s\r\n" % (len(x), x)
    return out


def conn(port, timeout=10):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s


def readn(s, nlines):
    buf = b""
    while buf.count(b"\r\n") < nlines:
        d = s.recv(1 << 16)
        if not d:
            raise EOFError("server closed")
        buf += d
    return buf


def note(kind, detail):
    if not STALL:
        STALL.append((kind, detail, time.time()))
    STOP.set()


# --------------------------------------------------------------------------- load
def loader(port, keys, pipeline, ratio_w, idx):
    try:
        s = conn(port, timeout=30)
    except Exception as e:
        note("loader-connect", repr(e))
        return
    n = len(keys)
    i = idx
    val = b"v" * 64
    try:
        while not STOP.is_set():
            batch = b""
            for j in range(pipeline):
                k = keys[(i + j) % n]
                if (i + j) % 10 < ratio_w:
                    batch += cmd("SET", k, val)
                else:
                    batch += cmd("GET", k)
            i += pipeline
            s.sendall(batch)
            readn(s, pipeline)
            OPS[0] += pipeline
    except socket.timeout:
        note("loader-timeout", "loader %d: no reply for 30s" % idx)
    except Exception as e:
        if not STOP.is_set():
            note("loader-error", "loader %d: %r" % (idx, e))


# ---------------------------------------------------------------------- resharder
def resharder(port, lo, hi, src, dst, log):
    """Drive cutovers of [lo,hi) back and forth between src and dst.

    Deliberately does NOT poll DEBUG RESHARD STATUS. STATUS runs migRangeChecksum over the WHOLE
    shard (rdbSaveObject per key) on the IO thread that received it — with a real dataset that
    parks a fence producer for seconds and manufactures a stall of its own, which would then get
    misclassified as the bug under investigation. START/CUTOVER are pure atomic flips; a rejected
    START is exactly the "a migration is already active" signal STATUS was being polled for.
    (In shared-kv mode scan_done is published 1 at arm, so CUTOVER needs no scan wait.)
    """
    try:
        s = conn(port, timeout=30)
    except Exception as e:
        note("resharder-connect", repr(e))
        return
    stuck = 0
    try:
        while not STOP.is_set():
            s.sendall(cmd("DEBUG", "RESHARD", "START", str(lo), str(hi), str(src), str(dst)))
            if b"+OK" not in readn(s, 1):
                ARM_ERRS[0] += 1
                stuck += 1
                if stuck > 4000:            # ~20s of nothing but refusals
                    note("reshard-stuck-active",
                         "DEBUG RESHARD START refused for 20s straight — a migration armed and "
                         "never completed (server still replies)")
                    return
                time.sleep(0.005)
                src, dst = dst, src         # the balancer may own the boundary; try the other way
                continue
            stuck = 0
            s.sendall(cmd("DEBUG", "RESHARD", "CUTOVER"))
            if b"+OK" in readn(s, 1):
                CUTOVERS[0] += 1
            src, dst = dst, src
    except socket.timeout:
        note("resharder-timeout", "DEBUG RESHARD command got no reply for 30s")
    except Exception as e:
        if not STOP.is_set():
            note("resharder-error", repr(e))


# ------------------------------------------------------------------------ watchdog
def watchdog(port, deadline_s, log):
    """Two independent liveness probes on every round:
         held  - a long-lived connection PINGing (does an ESTABLISHED client still get served?)
         fresh - a brand new connect + PING (does the listener still accept AND serve?)
    """
    try:
        held = conn(port, timeout=deadline_s)
    except Exception as e:
        note("watchdog-connect", repr(e))
        return
    while not STOP.is_set():
        t0 = time.time()
        try:
            held.settimeout(deadline_s)
            held.sendall(cmd("PING"))
            readn(held, 1)
        except Exception as e:
            note("held-ping-stall", "held connection PING no reply in %.1fs (%r)" % (time.time() - t0, e))
            return
        held_ms = (time.time() - t0) * 1000
        t1 = time.time()
        try:
            f = conn(port, timeout=deadline_s)
        except Exception as e:
            note("fresh-connect-refused", "connect() failed after %.1fs: %r" % (time.time() - t1, e))
            return
        try:
            f.settimeout(deadline_s)
            f.sendall(cmd("PING"))
            readn(f, 1)
            f.close()
        except Exception as e:
            note("fresh-ping-stall",
                 "connect SUCCEEDED but PING got no reply in %.1fs (%r)" % (time.time() - t1, e))
            return
        fresh_ms = (time.time() - t1) * 1000
        if held_ms > 1000 or fresh_ms > 1000:
            log("slow: held=%.0fms fresh=%.0fms cutovers=%d" % (held_ms, fresh_ms, CUTOVERS[0]))
        time.sleep(0.2)


# ---------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7899)
    ap.add_argument("--seconds", type=int, default=120)
    ap.add_argument("--keys", type=int, default=16)
    ap.add_argument("--conns", type=int, default=24)
    ap.add_argument("--pipeline", type=int, default=16)
    ap.add_argument("--write-pct", type=int, default=5, help="writes out of every 10 ops")
    ap.add_argument("--deadline", type=float, default=15.0, help="seconds before a PING counts as a stall")
    ap.add_argument("--drive-cutovers", action="store_true",
                    help="drive DEBUG RESHARD START/CUTOVER; default is to let the balancer trigger")
    ap.add_argument("--range", default="", help="lo:hi:src:dst override for the manual resharder")
    ap.add_argument("--logfile", default="")
    args = ap.parse_args()

    logf = open(args.logfile, "a", buffering=1) if args.logfile else None

    def log(m):
        line = "[%.1f] %s" % (time.time() % 100000, m)
        print(line, flush=True)
        if logf:
            logf.write(line + "\n")

    s = conn(args.port, timeout=20)
    s.sendall(cmd("DEBUG", "RESHARD", "PERWORKER"))
    d = b""
    while d.count(b"\r\n") < 1:
        d += s.recv(65536)
    nworkers = int(d.split(b"\r\n")[0][1:])
    while d.count(b"\r\n") < nworkers + 1:
        d += s.recv(65536)
    log("workers=%d" % nworkers)

    lo = hi = src = dst = 0
    keys = []
    if args.drive_cutovers or args.conns > 0:
        # Pick hot keys that all live inside ONE range, then migrate exactly that range: a random
        # 16-key set spreads over every shard and never puts real DRAINING pressure on the mover.
        if args.range:
            lo, hi, src, dst = [int(x) for x in args.range.split(":")]
        else:
            span = 16384 // nworkers
            lo, hi, src, dst = span // 2, span, 0, 1
        i = 0
        while len(keys) < args.keys and i < 200000:
            k = "hot:%d" % i
            i += 1
            s.sendall(cmd("DEBUG", "RESHARD", "FIND", k))
            r = readn(s, 1).decode(errors="replace")
            b = int(r.split("bucket=")[1].split()[0])
            if lo <= b < hi:
                keys.append(k)
        if len(keys) < args.keys:
            log("FAIL: could not find %d keys in [%d,%d)" % (args.keys, lo, hi))
            return 2
        log("hot keys (%d) all inside [%d,%d): %s" % (len(keys), lo, hi, ",".join(keys[:4]) + ",..."))
        for k in keys:
            s.sendall(cmd("SET", k, "seed"))
        readn(s, len(keys))
    s.close()

    threads = [threading.Thread(target=loader,
                                args=(args.port, keys, args.pipeline, args.write_pct, i),
                                daemon=True) for i in range(args.conns)]
    threads.append(threading.Thread(target=watchdog, args=(args.port, args.deadline, log), daemon=True))
    if args.drive_cutovers:
        threads.append(threading.Thread(target=resharder,
                                        args=(args.port, lo, hi, src, dst, log), daemon=True))
    for t in threads:
        t.start()

    t_end = time.time() + args.seconds
    last = 0
    while time.time() < t_end and not STOP.is_set():
        time.sleep(1.0)
        log("t=%3ds ops=%d (+%d) cutovers=%d arm_errs=%d"
            % (args.seconds - int(t_end - time.time()), OPS[0], OPS[0] - last, CUTOVERS[0], ARM_ERRS[0]))
        last = OPS[0]

    if STALL:
        kind, detail, _ = STALL[0]
        log("STALL	%s	%s	cutovers=%d ops=%d" % (kind, detail, CUTOVERS[0], OPS[0]))
        return 3
    STOP.set()
    log("no-stall	cutovers=%d ops=%d arm_errs=%d" % (CUTOVERS[0], OPS[0], ARM_ERRS[0]))
    if args.drive_cutovers and CUTOVERS[0] == 0:
        log("VACUOUS: zero cutovers completed — the window was never entered")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
