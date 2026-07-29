#!/usr/bin/env python3
"""Cross-shard MSET churn with value verification -- the check tomokv-mset-move needs.

WHY THIS SHAPE. With the knob ON, csAppendMsetValue hands the value robj to the owning worker
instead of copying it, relinquishing the head's argv slot via argv_released_mask. A mistake there
is a USE-AFTER-FREE or a double free, not a wrong answer, so the test must (a) run under ASAN to
see the memory error at all, and (b) still verify values, because a UAF that happens to read intact
memory shows up only as a wrong value.

So every iteration writes a batch of keys with values it can predict, reads them back and compares
byte for byte, then DELETEs and rewrites the same keys to force the allocator to reuse the freed
blocks -- a stale pointer that was merely dangling becomes a wrong value or an ASAN report.

Key names are deliberately unclustered so a batch spans several shards: a same-shard MSET never
reaches the cross-shard builder at all, and would test nothing (the local-fast path short-circuits
it). Value LENGTHS vary across the embed/heap boundary so both robj representations are exercised.

Usage: mset_move_churn.py <port> [seconds]   -> prints one PASS/FAIL line, exit 1 on failure.
"""
import socket, sys, random, threading, time

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 7893
SECS = float(sys.argv[2]) if len(sys.argv) > 2 else 25.0
NTHREAD = 6

errs = []


def enc(*a):  # noqa: E302
    o = f"*{len(a)}\r\n".encode()
    for x in a:
        b = x if isinstance(x, bytes) else str(x).encode()
        o += b"$%d\r\n%s\r\n" % (len(b), b)
    return o


def rd_line(s, buf):
    while b"\r\n" not in buf[0]:
        d = s.recv(1 << 20)
        if not d:
            raise IOError("closed")
        buf[0] += d
    line, _, rest = buf[0].partition(b"\r\n")
    buf[0] = rest
    return line


def rd_bulk(s, buf):
    """Read one RESP bulk string (or nil) without guessing at reply boundaries."""
    hdr = rd_line(s, buf)
    if hdr == b"$-1":
        return None
    n = int(hdr[1:])
    while len(buf[0]) < n + 2:
        d = s.recv(1 << 20)
        if not d:
            raise IOError("closed")
        buf[0] += d
    v, buf[0] = buf[0][:n], buf[0][n + 2:]
    return v


def worker(tid):
    s = socket.create_connection(("127.0.0.1", PORT))
    s.settimeout(60)
    buf = [b""]
    end = time.time() + SECS
    it = 0
    try:
        while time.time() < end:
            it += 1
            n = random.randint(3, 24)
            # scattered names => the batch spans shards => the cross-shard builder actually runs
            keys = [f"mm:{tid}:{random.randrange(4096)}:{random.randrange(64)}" for _ in range(n)]
            exp = {}
            args = []
            for k in keys:
                # straddle the embed/heap boundary in both directions
                v = f"{tid}-{it}-" + "v" * random.choice((8, 40, 60, 80, 300, 3000))
                exp[k] = v.encode()
                args += [k, v]
            s.sendall(enc("MSET", *args))
            if rd_line(s, buf) != b"+OK":
                errs.append((tid, it, "mset-not-ok"))
                continue
            uk = list(exp)
            s.sendall(enc("MGET", *uk))
            hdr = rd_line(s, buf)
            if hdr != b"*%d" % len(uk):
                errs.append((tid, it, f"mget-hdr {hdr!r}"))
                continue
            for k in uk:
                got = rd_bulk(s, buf)
                if got != exp[k]:
                    errs.append((tid, it, k, (got or b"")[:24], exp[k][:24]))
            # free then immediately reuse the same keys: a dangling value pointer that survived
            # the first read stops surviving once the allocator hands the block back out.
            s.sendall(enc("DEL", *uk))
            rd_line(s, buf)
            s.sendall(enc("MSET", *sum(([k, exp[k].decode()] for k in uk), [])))
            rd_line(s, buf)
            s.sendall(enc("MGET", *uk))
            rd_line(s, buf)
            for k in uk:
                if rd_bulk(s, buf) != exp[k]:
                    errs.append((tid, it, k, "after-reuse"))
    except Exception as e:
        errs.append((tid, "exc", repr(e)))
    finally:
        try:
            s.close()
        except Exception:
            pass


def mset_moved():
    """tomokv_xshard_mset_moved, or -1 if unreadable. Sampled BEFORE and AFTER: the counter is
    monotonic for the server's lifetime, so an absolute value proves the arm ran at some point in
    that process, not during THIS run. Measured the hard way -- reading it absolute made a
    knob-OFF run report the previous knob-ON run's total and look like evidence."""
    try:
        s = socket.create_connection(("127.0.0.1", PORT))
        s.settimeout(10)
        s.sendall(enc("INFO", "stats"))
        buf = [b""]
        n = int(rd_line(s, buf)[1:])
        while len(buf[0]) < n + 2:
            buf[0] += s.recv(1 << 20)
        v = -1
        for ln in buf[0][:n].split(b"\r\n"):
            if ln.startswith(b"tomokv_xshard_mset_moved:"):
                v = int(ln.split(b":")[1])
        s.close()
        return v
    except Exception:
        return -1


moved0 = mset_moved()
ths = [threading.Thread(target=worker, args=(i,)) for i in range(NTHREAD)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join(timeout=SECS + 90)

# A server that died mid-run must not read as "0 mismatches", and neither must a run that never
# took the MOVE arm.
alive = False
try:
    s = socket.create_connection(("127.0.0.1", PORT))
    s.settimeout(10)
    s.sendall(enc("PING"))
    alive = s.recv(64).startswith(b"+PONG")
    s.close()
except Exception as e:
    errs.append(("ping", repr(e)))
moved = mset_moved() - moved0 if moved0 >= 0 else -1

# --no-move asserts the CLOSED gate instead: run it with the knob off and the arm must not be
# entered at all. The two invocations together are what make the ON run's result attributable.
expect_move = "--no-move" not in sys.argv
gate_ok = (moved > 0) if expect_move else (moved == 0)
ok = not errs and alive and gate_ok
print(f"mset-move-churn{'-off' if not expect_move else ''}\t{'PASS' if ok else 'FAIL'}\t"
      f"{time.time()-t0:.0f}s threads={NTHREAD} alive={int(alive)} "
      f"moved_delta={moved} gate={'open' if expect_move else 'closed'} ok={int(gate_ok)} "
      f"mismatches={len(errs)} {errs[:4]}")
sys.exit(0 if ok else 1)
