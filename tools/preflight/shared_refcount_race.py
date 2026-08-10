#!/usr/bin/env python3
"""Discriminating probe for the shared-verb refcount race (P0, pre-existing).

THE DEFECT. `shared.del`, `shared.srem`, `shared.pexpireat`, `shared.hpersist` &c are process-global
robjs holding command names used during propagation. robj.refcount is a 23-bit bitfield packed with
type:4/encoding:4/iskvobj:1 into ONE 32-bit word, so `++`/`--` is a whole-word load-modify-store with
no atomicity. In stock Redis that is safe because commands run on one thread. In this fork the
propagating commands are WORKER-whitelisted, so N workers execute that read-modify-write on the same
word concurrently. Balanced incr/decr pairs then perform an unbiased random walk with an absorbing
barrier at 0; reaching it frees the global and the next toucher panics:

    illegal decrRefCount for object with refcount 0  (object.c)

WHY THIS SHAPE. The panic was observed at propagateDeletion <- deleteExpiredKeyAndPropagate <-
existsCommand on a worker, so lane A reproduces exactly that: a large population of short-TTL keys
read concurrently from many connections, making every reader trigger a lazy expiry that refcounts
shared.del/shared.unlink. Lanes B-D drive three OTHER verbs (SREM via SPOP, PERSIST/PEXPIREAT via
GETEX, HPERSIST/HPEXPIREAT/FIELDS via HEXPIRE) because those reach different constants through
different commands -- a fix that pinned only the DEL/UNLINK pair would pass lane A and fail here.

DISCRIMINATION. This file is worthless unless it FAILS on a build that still has the defect. It is
therefore run against BOTH arms by shared_refcount_race.sh, which requires unfixed=CRASH and
fixed=CLEAN. A green run of the fixed arm alone proves nothing -- that mistake has been made
repeatedly in this project (see the vacuous-validation ledger in docs/BUGS.md).
"""
import socket, sys, threading, time, random

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7898
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 45.0
THREADS = int(sys.argv[3]) if len(sys.argv) > 3 else 16
NKEYS = 4000
WINDOW = 8   # outstanding batches per lane; see the DEPTH MATTERS note below

stop = threading.Event()
ops = [0] * THREADS
died = []


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


def lane(tid):
    """Each thread pipelines one verb family so many workers hit the same constant at once."""
    try:
        s = conn()
    except Exception as e:
        died.append("connect: %r" % (e,)); return
    rnd = random.Random(tid * 7919)
    fam = tid % 4
    pend = []
    try:
        while not stop.is_set():
            batch = b""
            n = 0
            for _ in range(32):
                k = rnd.randrange(NKEYS)
                if fam == 0:
                    # A: lazy-expire -> propagateDeletion -> shared.del / shared.unlink
                    batch += cmd("SET", "rc:%d" % k, "v", "PX", "12"); n += 1
                    batch += cmd("EXISTS", "rc:%d" % k); n += 1
                    batch += cmd("GET", "rc:%d" % k); n += 1
                elif fam == 1:
                    # B: SPOP -> propagate SREM -> shared.srem
                    batch += cmd("SADD", "rs:%d" % k, "a", "b", "c", "d"); n += 1
                    batch += cmd("SPOP", "rs:%d" % k); n += 1
                elif fam == 2:
                    # C: GETEX -> propagate PEXPIREAT / PERSIST -> shared.pexpireat, shared.persist
                    batch += cmd("SET", "rg:%d" % k, "v"); n += 1
                    batch += cmd("GETEX", "rg:%d" % k, "EX", "100"); n += 1
                    batch += cmd("GETEX", "rg:%d" % k, "PERSIST"); n += 1
                else:
                    # D: HEXPIRE/HPERSIST -> shared.hpexpireat, shared.hpersist, shared.fields
                    batch += cmd("HSET", "rh:%d" % k, "f", "v"); n += 1
                    batch += cmd("HEXPIRE", "rh:%d" % k, "100", "FIELDS", "1", "f"); n += 1
                    batch += cmd("HPERSIST", "rh:%d" % k, "FIELDS", "1", "f"); n += 1
            # Self-synchronising batch terminator. Counting \r\n does NOT work: a bulk reply
            # ($3\r\nabc\r\n) contains two, so the count overshoots, the read loop exits early,
            # leftover bytes desync every later batch and the lane eventually blocks in recv --
            # which this probe would then misreport as a server hang. Trailing PING is exact.
            # DEPTH MATTERS. The race window is two adjacent instructions on one word, so it is
            # only hit when several workers are inside propagation AT ONCE. Draining each batch
            # before sending the next serialises the server and the defect stops reproducing --
            # measured: a drain-per-batch run survived 60s where a deeply-pipelined one panicked
            # in ~2s. So keep WINDOW batches outstanding, and sync on the PING sentinels.
            pend.append((batch + cmd("PING"), n))
            if len(pend) < WINDOW:
                continue
            s.sendall(b"".join(b for b, _ in pend))
            want = len(pend)
            buf = b""
            while buf.count(b"+PONG\r\n") < want:
                d = s.recv(262144)
                if not d:
                    raise ConnectionError("server closed (likely panic)")
                buf += d
                if len(buf) > 128 << 20:
                    raise ConnectionError("runaway reply stream")
            ops[tid] += sum(x for _, x in pend)
            pend = []
    except Exception as e:
        died.append("t%d: %r" % (tid, e))


def main():
    try:
        c = conn(); c.sendall(cmd("PING")); c.recv(100)
    except Exception as e:
        print("shared_refcount_race: SKIP (no server): %r" % (e,)); sys.exit(2)

    ts = [threading.Thread(target=lane, args=(i,), daemon=True) for i in range(THREADS)]
    for t in ts:
        t.start()
    time.sleep(SECS)
    stop.set()
    for t in ts:
        t.join(timeout=5)

    total = sum(ops)
    # Retry the liveness check: a single refused connect right after 16 lanes stop hammering can
    # be listen-backlog pressure, not a dead server. Report WHY it failed so a future reader can
    # tell a probe artefact from a real death.
    alive, why = 0, ""
    for _ in range(5):
        try:
            c2 = conn(); c2.sendall(cmd("PING"))
            if b"PONG" in c2.recv(100):
                alive = 1; break
        except Exception as e:
            why = repr(e); time.sleep(1.0)
    if not alive and why:
        print("   liveness check failed:", why)
    print("shared_refcount_race: ops=%d alive=%d lanes_died=%d" % (total, alive, len(died)))
    for d in died[:4]:
        print("   ", d)
    # A run that did no work cannot discriminate -- refuse to call that a pass.
    if total < 50000:
        print("shared_refcount_race: SKIP (only %d ops; probe did not load the race)" % total)
        sys.exit(2)
    sys.exit(0 if alive else 1)


if __name__ == "__main__":
    main()
