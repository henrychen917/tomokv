#!/usr/bin/env python3
"""perfab.py -- INDICATIVE loopback A/B for one server on <port>.

Cells: plain GET/SET at p32 (the hot path the fix must not touch), a cross-shard read (MGET), a
single-wave cross-shard write (DEL of 2 keys), and the two-hop store family, which is the only
path the fix changes.  The store cells are run BOTH bare (a pipeline of stores only) and MIXED
(3 plain ops between stores), because the fix's cost is exactly "older in-flight ops must retire
first" and only the mixed shape can pay it.
"""
import socket, sys, time

HOST, PORT = sys.argv[1], int(sys.argv[2])
REPS = int(sys.argv[3]) if len(sys.argv) > 3 else 5
N = 20000


def enc(a):
    o = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str): x = x.encode()
        o += b"$%d\r\n" % len(x) + x + b"\r\n"
    return o


def read_reply(f):
    line = f.readline()
    if not line: raise EOFError
    t = line[:1]
    if t in b"+-:,#(_": return line
    if t in b"$=":
        n = int(line[1:-2]); return line if n == -1 else line + f.read(n + 2)
    if t in b"*%~>":
        n = int(line[1:-2])
        if n == -1: return line
        if t == b"%": n *= 2
        return line + b"".join(read_reply(f) for _ in range(n))
    raise RuntimeError(line)


s = socket.create_connection((HOST, PORT), timeout=120)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = s.makefile("rb")
s.sendall(enc(["FLUSHALL"])); read_reply(f)
s.sendall(enc(["ZADD", "pab:src", "1", "a", "2", "b", "3", "c"])); read_reply(f)
s.sendall(enc(["ZADD", "pab:src2", "2", "b", "4", "d"])); read_reply(f)
for k in ("pab:sa", "pab:sb"):
    s.sendall(enc(["SET", k, "v"])); read_reply(f)
for i in range(2000):
    s.sendall(enc(["SET", "pab:k%d" % i, "value"])); read_reply(f)

CELLS = {
    "get_p32":      [["GET", "pab:k%d" % (i % 2000)] for i in range(N)],
    "set_p32":      [["SET", "pab:k%d" % (i % 2000), "value"] for i in range(N)],
    "mget2_p32":    [["MGET", "pab:sa", "pab:sb"] for _ in range(N // 4)],
    "del2_p32":     [["DEL", "pab:na%d" % i, "pab:nb%d" % i] for i in range(N // 4)],
    "zrangestore":  [["ZRANGESTORE", "pab:d%d" % (i % 8), "pab:src", "0", "-1"]
                     for i in range(N // 10)],
    "zdiffstore":   [["ZDIFFSTORE", "pab:d%d" % (i % 8), "2", "pab:src", "pab:src2"]
                     for i in range(N // 10)],
}
mixed = []
for i in range(N // 10):
    mixed += [["GET", "pab:k%d" % (i % 2000)], ["GET", "pab:sa"], ["GET", "pab:sb"],
              ["ZDIFFSTORE", "pab:d%d" % (i % 8), "2", "pab:src", "pab:src2"]]
CELLS["mixed_store"] = mixed
BATCH = 32

results = {}
for rep in range(REPS):
    for name, ops in CELLS.items():
        payload = [b"".join(enc(o) for o in ops[i:i + BATCH]) for i in range(0, len(ops), BATCH)]
        t0 = time.time()
        for chunk_i, chunk in enumerate(payload):
            s.sendall(chunk)
            for _ in range(min(BATCH, len(ops) - chunk_i * BATCH)): read_reply(f)
        dt = time.time() - t0
        results.setdefault(name, []).append(len(ops) / dt)

for name in CELLS:
    v = sorted(results[name])
    print("%-14s best %9.0f  median %9.0f ops/s" % (name, v[-1], v[len(v) // 2]))
