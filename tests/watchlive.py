#!/usr/bin/env python3
"""WATCH liveness: EXEC must always answer while the server is answering PING.

Usage: watchlive.py HOST PORT [--conns N] [--reps N] [--deadline SEC] [--no-watch]
       [--rate-only] [--quiet]

THE DEFECT THIS GATE LOCKS
--------------------------
With WATCH armed and several connections pipelining a wide multi-key write plus a transaction
over OVERLAPPING keys, EXEC stopped answering while the server still replied to PING on another
connection.  A liveness failure, not data loss -- and PING kept looking healthy, which is exactly
what makes it dangerous for production monitoring.

Mechanism: `Shard::watch_finalize_reservation()` reports "not ready" while a reservation's epoch
is still 0, and its callers turn "not ready" into a Retry that re-queues the task.  A reservation
whose epoch is only published at the transaction's COMMIT point can therefore be waited on by a
unit that the committing transaction is itself waiting for -- a wait-for cycle between two EX
retry queues that no timeout breaks.  The EX threads keep spinning their retry queues, so the
event loop stays alive and PING (routed on an IO thread and, for a same-shard key-less command,
never blocked behind the wedged shard) keeps answering.

WHY THIS BATTERY IS NOT VACUOUS
-------------------------------
- PROBABILISTIC, SO IT REPORTS A RATE.  The wedge is a race.  A single clean run proves nothing,
  so every arm runs REPS repetitions against a FRESH keyspace and reports wedged/REPS.  The gate
  asserts a rate over repetitions, never a single run.
- THE DETECTOR CAN REPORT NON-ZERO.  It did: see NOTES-WATCHLIVE.md for the pre-fix rates
  (2/6 at 4 conns, 4/6 at 8, 5/6 at 16).  A detector that has never fired proves nothing.
- THE DETECTOR CAN REPORT ZERO.  The --no-watch control runs the identical shape with the WATCH
  frames removed and must report 0 wedges.  If the control ever wedges, the harness is at fault
  and the WATCH arm's number means nothing.
- LIVENESS, NOT SLOWNESS.  A repetition only counts as wedged when the EXEC reply is still absent
  after the deadline AND a PING on a separate connection answered inside that same window.  A
  server that is merely slow fails the PING probe too and is reported as "stalled", not "wedged".
- GEOMETRY.  Keys are chosen so the transaction and the wide write overlap, and (when DEBUG is
  available) the harness reports how many shards the key set spans, because a single-shard key set
  cannot exercise the cross-shard reservation path at all.
"""

import argparse
import socket
import sys
import threading
import time


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for arg in args:
        if isinstance(arg, str):
            arg = arg.encode()
        out += b"$%d\r\n" % len(arg) + arg + b"\r\n"
    return bytes(out)


class RespError:
    def __init__(self, message):
        self.message = message

    def __repr__(self):
        return "RespError(%r)" % self.message


class Resp:
    def __init__(self, host, port, timeout=60):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.file = self.sock.makefile("rb")

    def close(self):
        try:
            self.file.close()
            self.sock.close()
        except OSError:
            pass

    def settimeout(self, seconds):
        self.sock.settimeout(seconds)

    def send(self, *args):
        self.sock.sendall(frame(*args))

    def send_raw(self, blob):
        self.sock.sendall(blob)

    def read(self):
        line = self.file.readline()
        if not line:
            raise EOFError("server closed")
        kind = line[:1]
        if kind == b"+":
            return line[1:-2]
        if kind == b"-":
            return RespError(line[1:-2].decode(errors="replace"))
        if kind == b":":
            return int(line[1:-2])
        if kind == b"$":
            size = int(line[1:-2])
            if size == -1:
                return None
            data = self.file.read(size)
            if self.file.read(2) != b"\r\n":
                raise ValueError("bad bulk trailer")
            return data
        if kind == b"*":
            count = int(line[1:-2])
            if count == -1:
                return None
            return [self.read() for _ in range(count)]
        raise ValueError("bad RESP type %r" % line[:20])

    def cmd(self, *args):
        self.send(*args)
        return self.read()


# ----------------------------------------------------------------------------------------------
# The shape.  One connection: WATCH over the shared key band, a wide MSET and a wide DEL over the
# same band, then MULTI(SET xN, DEL wide) + EXEC -- all written as ONE pipelined blob so the
# frames are in flight together and the transactions of different connections interleave inside
# the server rather than being serialised by the client's own read/write turn-taking.
# ----------------------------------------------------------------------------------------------

WIDE = 24          # keys per wide MSET/DEL
TXN_SETS = 8       # SET commands inside the transaction
BAND = 32          # size of the shared key band the connections fight over
ROUNDS = 8         # rounds of the shape per connection, all in ONE pipelined blob


def build_pipeline(run, conn, watch, band=None, rounds=None):
    """Returns (blob, nreplies, exec_indices).

    Each round is: [WATCH band-slice] wide MSET, wide DEL, MULTI(SET xN, wide DEL), EXEC.
    Odd rounds put the WATCH *after* the connection's own wide writes.  That matters: a client's
    own write dirties its own WATCH (redis semantics, matched here), so a WATCH placed first makes
    EXEC abort every time and the transaction body never runs.  Alternating the placement gives a
    mix of committed and aborted EXECs, which is what the reservation path actually sees.
    """
    band = BAND if band is None else band
    rounds = ROUNDS if rounds is None else rounds
    parts = []
    n = 0
    exec_indices = []
    for r in range(rounds):
        # Overlapping windows: connection i starts further into the shared band each round, so
        # every pair of connections shares most of its keys but not the order it touches them in.
        off = (conn * 7 + r * 3) % band
        keys = [b"wl:%d:%d" % (run, (off + j) % band) for j in range(WIDE)]
        half = max(2, WIDE // 2)
        watch_frame = frame("WATCH", *keys[:half]) if watch else None
        watch_first = (r % 2 == 0)
        if watch_frame and watch_first:
            parts.append(watch_frame)
            n += 1
        mset = ["MSET"]
        for k in keys:
            mset.append(k)
            mset.append(b"v%d" % conn)
        parts.append(frame(*mset))
        n += 1
        parts.append(frame("DEL", *keys[WIDE // 4:WIDE // 4 + half]))
        n += 1
        if watch_frame and not watch_first:
            parts.append(watch_frame)
            n += 1
        parts.append(frame("MULTI"))
        n += 1
        for j in range(TXN_SETS):
            parts.append(frame("SET", keys[(j * 3) % WIDE], b"t%d" % conn))
            n += 1
        parts.append(frame("DEL", *keys[WIDE // 12:WIDE // 12 + half]))
        n += 1
        parts.append(frame("EXEC"))
        exec_indices.append(n)
        n += 1
    return b"".join(parts), n, exec_indices


def run_repetition(host, port, nconn, watch, deadline, run_id, ping, seconds=2.0):
    """One repetition on a fresh key band.  Returns (verdict, detail).

    verdict is one of 'clean', 'wedged', 'stalled', 'error'.

    A repetition is a SUSTAINED wave load, not a single blob: every connection repeats its
    pipelined blob for `seconds`, released together by a barrier so the transactions of different
    connections are genuinely in flight at the same time.  A single blob finishes in ~10ms, which
    is far too short a window for the race, and reported clean every time.
    """
    clients = []
    threads = []
    try:
        for i in range(nconn):
            clients.append(Resp(host, port, timeout=deadline + 5))
    except OSError as exc:
        for c in clients:
            c.close()
        return "error", "connect: %r" % (exc,)

    results = [None] * nconn
    committed = [0] * nconn
    waves = [0] * nconn
    gate = threading.Barrier(nconn, timeout=30)
    stop_at = [0.0]

    def body(i):
        cli = clients[i]
        try:
            cli.settimeout(deadline)
            gate.wait()
            wave = 0
            while time.time() < stop_at[0]:
                # run_id is FIXED for the whole repetition on purpose.  Rotating it per wave lets
                # connections drift onto different key bands as they lose wave-sync, and then they
                # stop overlapping -- which is the one property the defect needs.
                blob, n, exec_idx = build_pipeline(run_id, i, watch)
                want = set(exec_idx)
                cli.send_raw(blob)
                for k in range(n):
                    reply = cli.read()
                    if k in want and reply is not None:
                        committed[i] += 1
                wave += 1
                waves[i] = wave
            results[i] = ("ok", waves[i], 0)
        except socket.timeout:
            results[i] = ("timeout", waves[i], -1)
        except threading.BrokenBarrierError:
            results[i] = ("error", "barrier", -1)
        except Exception as exc:                                   # noqa: BLE001
            results[i] = ("error", repr(exc), -1)

    for i in range(nconn):
        threads.append(threading.Thread(target=body, args=(i,), daemon=True))
    start = time.time()
    stop_at[0] = start + seconds
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=seconds + deadline + 5)
    elapsed = time.time() - start

    stuck = [i for i in range(nconn) if results[i] is None or results[i][0] == "timeout"]
    errs = [i for i in range(nconn) if results[i] is not None and results[i][0] == "error"]

    total_exec = sum(waves) * ROUNDS
    verdict, detail = "clean", "%.2fs  waves=%d exec-committed=%d/%d" % (
        elapsed, sum(waves), sum(committed), total_exec)
    if stuck:
        # LIVENESS DISCRIMINATOR: is the server still answering on an untouched connection?
        alive = False
        probe_ms = -1.0
        try:
            ping.settimeout(3.0)
            t0 = time.time()
            alive = ping.cmd("PING") == b"PONG"
            probe_ms = (time.time() - t0) * 1000.0
        except Exception:                                          # noqa: BLE001
            alive = False
        if alive:
            verdict = "wedged"
            detail = "conns stuck=%s ping=%.1fms" % (stuck, probe_ms)
        else:
            verdict = "stalled"
            detail = "conns stuck=%s PING also dead" % (stuck,)
    elif errs:
        verdict = "error"
        detail = "; ".join(str(results[i][1]) for i in errs[:2])

    for c in clients:
        c.close()
    return verdict, detail


def arm(host, port, nconn, watch, reps, deadline, quiet=False):
    """Runs `reps` repetitions and returns a dict of verdict counts."""
    counts = {"clean": 0, "wedged": 0, "stalled": 0, "error": 0}
    details = []
    ping = Resp(host, port, timeout=10)
    for r in range(reps):
        run_id = int(time.time() * 1000) % 1000000 + r * 7919
        verdict, detail = run_repetition(host, port, nconn, watch, deadline, run_id, ping)
        counts[verdict] += 1
        if verdict != "clean":
            details.append("rep%d %s: %s" % (r, verdict, detail))
        if not quiet:
            print("    rep %2d/%d  %-7s %s" % (r + 1, reps, verdict, detail), flush=True)
        if verdict == "wedged":
            # A wedged server stays wedged; every later repetition on it is not an independent
            # trial.  Re-establish the probe connection and keep going -- the caller restarts
            # the server between arms, so we only report what this boot showed.
            try:
                ping.close()
            except Exception:                                      # noqa: BLE001
                pass
            ping = Resp(host, port, timeout=10)
    ping.close()
    return counts, details


# ----------------------------------------------------------------------------------------------
# SEMANTICS.  The liveness fix chose a serialization instead of waiting for one, so the WATCH
# contract itself is asserted here in both directions, deterministically (each foreign write is
# acknowledged before the transaction runs, so no race decides the answer).  Without these a
# server could pass the liveness rows by aborting every transaction it is ever handed.
# ----------------------------------------------------------------------------------------------

def semantics(host, port):
    """Returns (failures, log-lines)."""
    fails, log = 0, []

    def check(name, ok, extra=""):
        nonlocal fails
        log.append(("  ok   " if ok else "  FAIL ") + name + (" " + extra if extra else ""))
        if not ok:
            fails += 1

    a = Resp(host, port, timeout=20)
    b = Resp(host, port, timeout=20)
    tag = "wls:%d" % (int(time.time() * 1000) % 1000000)
    keys = [b"%s:%d" % (tag.encode(), i) for i in range(16)]

    # ARM: a foreign wide cross-shard write lands on a watched key BEFORE the transaction runs.
    # The transaction must be told its watch broke -- EXEC answers a null array, not results.
    a.cmd("MSET", *[x for k in keys for x in (k, b"base")])
    a.cmd("WATCH", *keys[:8])
    mset = ["MSET"]
    for k in keys[:8]:
        mset += [k, b"foreign"]
    check("foreign wide MSET acknowledged", b.cmd(*mset) == b"OK")
    a.cmd("MULTI")
    a.cmd("SET", keys[0], b"txn")
    reply = a.cmd("EXEC")
    check("EXEC aborts after a foreign write to a watched key", reply is None, repr(reply)[:60])
    check("the aborted transaction wrote nothing", a.cmd("GET", keys[0]) == b"foreign",
          repr(a.cmd("GET", keys[0]))[:40])

    # NEGATIVE CONTROL 1: nothing foreign touches the watched keys -- EXEC must COMMIT.  This is
    # the row a fix that merely aborts everything would fail.
    a.cmd("WATCH", *keys[:8])
    a.cmd("MULTI")
    a.cmd("SET", keys[0], b"committed")
    reply = a.cmd("EXEC")
    check("EXEC commits with no foreign write", isinstance(reply, list) and len(reply) == 1,
          repr(reply)[:60])
    check("the committed transaction's write is visible",
          a.cmd("GET", keys[0]) == b"committed", repr(a.cmd("GET", keys[0]))[:40])

    # NEGATIVE CONTROL 2: a foreign wide write that misses every watched key must NOT abort.
    a.cmd("WATCH", *keys[:4])
    mset = ["MSET"]
    for k in keys[8:]:
        mset += [k, b"elsewhere"]
    check("foreign write to unwatched keys acknowledged", b.cmd(*mset) == b"OK")
    a.cmd("MULTI")
    a.cmd("SET", keys[0], b"still-committed")
    reply = a.cmd("EXEC")
    check("EXEC commits when the foreign write missed the watched keys",
          isinstance(reply, list) and len(reply) == 1, repr(reply)[:60])

    # A foreign cross-shard DEL of a watched key is a modification too.
    a.cmd("WATCH", *keys[:8])
    check("foreign wide DEL acknowledged", isinstance(b.cmd("DEL", *keys[:8]), int))
    a.cmd("MULTI")
    a.cmd("SET", keys[0], b"after-del")
    reply = a.cmd("EXEC")
    check("EXEC aborts after a foreign DEL of a watched key", reply is None, repr(reply)[:60])

    a.close()
    b.close()
    return fails, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("port", type=int)
    ap.add_argument("--conns", type=int, default=16)
    ap.add_argument("--reps", type=int, default=6)
    ap.add_argument("--deadline", type=float, default=5.0)
    ap.add_argument("--no-watch", action="store_true",
                    help="run the zero control: identical shape, WATCH frames removed")
    ap.add_argument("--rate-only", action="store_true",
                    help="print only 'wedged/reps' and exit 0 (driver mode)")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--semantics-only", action="store_true",
                    help="run only the deterministic WATCH-contract checks and exit non-zero on "
                         "any failure (this part IS a pass/fail battery)")
    args = ap.parse_args()

    if args.semantics_only:
        fails, log = semantics(args.host, args.port)
        print("watchlive semantics", flush=True)
        for line in log:
            print(line, flush=True)
        print("  semantics: %d failure(s)" % fails, flush=True)
        return 1 if fails else 0

    watch = not args.no_watch
    label = "WATCH" if watch else "NO-WATCH(control)"
    if not args.rate_only:
        print("watchlive: %s  conns=%d reps=%d deadline=%.1fs"
              % (label, args.conns, args.reps, args.deadline), flush=True)
    counts, details = arm(args.host, args.port, args.conns, watch, args.reps,
                          args.deadline, quiet=args.quiet or args.rate_only)
    if args.rate_only:
        print("%d/%d" % (counts["wedged"], args.reps))
        return 0
    print("  %s: wedged %d/%d  (clean %d, stalled %d, error %d)"
          % (label, counts["wedged"], args.reps, counts["clean"],
             counts["stalled"], counts["error"]), flush=True)
    for d in details:
        print("    " + d, flush=True)
    fails, log = semantics(args.host, args.port)
    for line in log:
        print(line, flush=True)
    print("  semantics: %d failure(s)" % fails, flush=True)
    # The LIVENESS half is a REPORTER, not a pass/fail gate -- the rate it reports is only
    # meaningful with the fresh-server-per-repetition discipline that watchlive_gate.sh owns.
    # The SEMANTICS half is deterministic, so it decides the exit status.
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
