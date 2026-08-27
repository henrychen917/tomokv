#!/usr/bin/env python3
"""INDICATIVE loopback throughput cells for the t-execfix A/B.

Shapes (all keep MVCC entries live, which is the ONLY condition under which the changed winner
comparison in atomic_resolve_internal executes at all -- with no pending entry the resolver returns
at its first line and the change is unreachable):
  mset       bare cross-shard MSET k_a v k_b v          -- the plain atomic group path
  msetget    cross-shard MSET interleaved with GET      -- resolver reads against a live chain
  execwrite  MULTI / SET k_a v / SET k_b v / EXEC       -- the transaction write path

Usage: abbench.py HOST PORT SECONDS SHAPE [PROCS] [CONNS] [DEPTH]
Prints one line: shape=<s> ops/s=<n>   (ops = pipeline units completed)
"""
import multiprocessing
import socket
import sys
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
SECONDS = float(sys.argv[3])
SHAPE = sys.argv[4]
PROCS = int(sys.argv[5]) if len(sys.argv) > 5 else 2
CONNS = int(sys.argv[6]) if len(sys.argv) > 6 else 8
DEPTH = int(sys.argv[7]) if len(sys.argv) > 7 else 32
VALUE = b"v" * 32
# ONE KEY PER SHARD, discovered with DEBUG SHARD at bench start.  The router's hash seed is drawn
# from the kernel at every boot, so a key set picked by name lands on a different shard->executor
# split on every boot and an A/B then measures the seed, not the binary (recorded by lane
# t-execiso).  Pairing shard i with shard i+1 gives every cell the same fan-out geometry on every
# boot: every group is exactly two owners.
KEYS = []


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        out += b"$%d\r\n" % len(a) + a + b"\r\n"
    return bytes(out)


def read_reply(f):
    line = f.readline()
    if not line:
        raise EOFError
    k = line[:1]
    if k in (b"+", b"-", b":"):
        return
    if k == b"$":
        n = int(line[1:-2])
        if n >= 0:
            f.read(n + 2)
        return
    if k == b"*":
        n = int(line[1:-2])
        if n > 0:
            for _ in range(n):
                read_reply(f)
        return
    raise ValueError(line)


def unit(i):
    """(bytes to send, number of RESP replies that come back) for one pipeline unit."""
    a = KEYS[i % len(KEYS)]
    b = KEYS[(i + 1) % len(KEYS)]
    if SHAPE == "mset":
        return frame("MSET", a, VALUE, b, VALUE), 1
    if SHAPE == "msetget":
        return frame("MSET", a, VALUE, b, VALUE) + frame("GET", a) + frame("GET", b), 3
    if SHAPE == "execwrite":
        return (frame("MULTI") + frame("SET", a, VALUE) + frame("SET", b, VALUE) +
                frame("EXEC")), 4
    raise SystemExit("unknown shape " + SHAPE)


def worker(index, keys, out):
    global KEYS
    KEYS = keys
    conns = []
    for c in range(CONNS):
        s = socket.create_connection((HOST, PORT), timeout=30)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        payload = bytearray()
        replies = 0
        for d in range(DEPTH):
            body, n = unit(index * 100003 + c * 1009 + d)
            payload += body
            replies += n
        conns.append((s, s.makefile("rb"), bytes(payload), replies))
    done = 0
    deadline = time.time() + SECONDS
    for s, _, payload, _ in conns:
        s.sendall(payload)
    while time.time() < deadline:
        for s, f, payload, replies in conns:
            for _ in range(replies):
                read_reply(f)
            done += DEPTH
            s.sendall(payload)
    # drain the last outstanding batch so the server is not left mid-pipeline
    for s, f, payload, replies in conns:
        try:
            for _ in range(replies):
                read_reply(f)
        except (EOFError, OSError):
            pass
        s.close()
    out.put(done)


if __name__ == "__main__":
    warm = socket.create_connection((HOST, PORT), timeout=30)
    wf = warm.makefile("rb")
    warm.sendall(frame("FLUSHALL"))
    read_reply(wf)

    def shard_of(key):
        warm.sendall(frame("DEBUG", "SHARD", key))
        line = wf.readline()
        if line[:1] != b":":
            raise SystemExit("DEBUG SHARD unavailable (boot --enable-debug-command yes): %r"
                             % line)
        return int(line[1:-2])

    per_shard = {}
    index = 0
    while index < 20000 and len(per_shard) < 64:
        key = "ab:%06d" % index
        per_shard.setdefault(shard_of(key), key)
        index += 1
        if len(per_shard) >= 16 and index > 4000:
            break
    KEYS = [per_shard[s] for s in sorted(per_shard)]
    batch = b"".join(frame("SET", k, VALUE) for k in KEYS)
    warm.sendall(batch)
    for _ in KEYS:
        read_reply(wf)
    warm.close()
    q = multiprocessing.Queue()
    procs = [multiprocessing.Process(target=worker, args=(i, KEYS, q)) for i in range(PROCS)]
    start = time.time()
    for p in procs:
        p.start()
    total = sum(q.get() for _ in procs)
    for p in procs:
        p.join()
    print("shape=%s ops/s=%d" % (SHAPE, int(total / (time.time() - start))))
