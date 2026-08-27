#!/usr/bin/env python3
"""INDICATIVE loopback EXEC throughput: MULTI / MGET <one key per shard> / EXEC, pipelined.

Every key holds a fixed-width value, so one transaction's reply is a constant number of bytes and
the client can measure completions by counting bytes instead of parsing RESP.  That keeps the
loadgen cheap enough (two cores) that the server is the thing being measured.

Usage: execbench.py HOST PORT SECONDS [PROCS] [CONNS_PER_PROC] [DEPTH] [SHAPE]
  SHAPE : exec (default) | bare | execlocal
          exec      MULTI / MGET k*/ EXEC             the shape this lane changed
          bare      MGET k*                           the same read without MULTI
          execlocal MULTI / GET k0 / EXEC             a transaction with no fan-out read: must be
                                                      untouched, because it registers no cut
"""
import multiprocessing
import socket
import sys
import time

HOST, PORT = sys.argv[1], int(sys.argv[2])
SECONDS = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0
PROCS = int(sys.argv[4]) if len(sys.argv) > 4 else 2
CONNS = int(sys.argv[5]) if len(sys.argv) > 5 else 4
DEPTH = int(sys.argv[6]) if len(sys.argv) > 6 else 16
SHAPE = sys.argv[7] if len(sys.argv) > 7 else "exec"
VALUE = b"v" * 8
NKEYS = 8


def frame(*args):
    out = bytearray(b"*%d\r\n" % len(args))
    for a in args:
        if isinstance(a, str):
            a = a.encode()
        out += b"$%d\r\n" % len(a) + a + b"\r\n"
    return bytes(out)


def pick_keys():
    """One key per shard, so the read fans out over every owner on every boot."""
    s = socket.create_connection((HOST, PORT), timeout=30)
    f = s.makefile("rb")

    def cmd(*a):
        s.sendall(frame(*a))
        line = f.readline()
        if line[:1] == b"$":
            n = int(line[1:-2])
            if n < 0:
                return None
            d = f.read(n)
            f.read(2)
            return d
        return line[1:-2]

    # ONE KEY PER SHARD, every shard.  The hash seed is redrawn at every boot, so a fixed count of
    # keys lands on a different shard->ex-thread split each time; with 8 keys over 4 executors that
    # lottery moved this cell between four discrete levels and an A/A control swung -42%..+72%.
    # Covering every shard makes each executor carry exactly nshards/n_ex fragments on every boot,
    # which is what makes the cell comparable across reboots at all.
    by_shard, probe = {}, 0
    while probe < 8000:
        key = "eb:%d" % probe
        who = cmd("DEBUG", "SHARD", key)
        try:
            who = int(who)
        except (TypeError, ValueError):
            by_shard = {i: "eb:%d" % i for i in range(NKEYS)}
            break
        by_shard.setdefault(who, key)
        probe += 1
    seen = set(by_shard)
    picked = [by_shard[k] for k in sorted(by_shard)]
    for key in picked:
        cmd("SET", key, VALUE.decode())
    f.close()
    s.close()
    return picked, sorted(seen)


def txn_bytes(keys):
    if SHAPE == "bare":
        req = frame("MGET", *keys)
        rep = len(b"*%d\r\n" % len(keys)) + len(keys) * (len(b"$8\r\n") + 8 + 2)
    elif SHAPE == "execlocal":
        req = frame("MULTI") + frame("GET", keys[0]) + frame("EXEC")
        rep = len(b"+OK\r\n") + len(b"+QUEUED\r\n") + len(b"*1\r\n") + len(b"$8\r\n") + 8 + 2
    else:
        req = frame("MULTI") + frame("MGET", *keys) + frame("EXEC")
        rep = (len(b"+OK\r\n") + len(b"+QUEUED\r\n") + len(b"*1\r\n") +
               len(b"*%d\r\n" % len(keys)) + len(keys) * (len(b"$8\r\n") + 8 + 2))
    return req, rep


def worker(keys, out):
    req, rep = txn_bytes(keys)
    burst = req * DEPTH
    want = rep * DEPTH
    socks = []
    for _ in range(CONNS):
        s = socket.create_connection((HOST, PORT), timeout=30)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        socks.append(s)
    done = 0
    deadline = time.time() + SECONDS
    started = time.time()
    for s in socks:
        s.sendall(burst)
    pending = {id(s): want for s in socks}
    while time.time() < deadline:
        for s in socks:
            data = s.recv(1 << 16)
            if not data:
                raise EOFError
            pending[id(s)] -= len(data)
            if pending[id(s)] <= 0:
                done += DEPTH
                pending[id(s)] = want
                s.sendall(burst)
    elapsed = time.time() - started
    for s in socks:
        s.close()
    out.put((done, elapsed))


if __name__ == "__main__":
    keys, span = pick_keys()
    queue = multiprocessing.Queue()
    procs = [multiprocessing.Process(target=worker, args=(keys, queue)) for _ in range(PROCS)]
    for p in procs:
        p.start()
    results = [queue.get() for _ in procs]
    for p in procs:
        p.join()
    total = sum(r[0] for r in results)
    elapsed = max(r[1] for r in results)
    print("%s shape=%s procs=%d conns=%d depth=%d owners=%s txn/s=%.0f"
          % (sys.argv[0].split("/")[-1], SHAPE, PROCS, CONNS, DEPTH, span, total / elapsed))
