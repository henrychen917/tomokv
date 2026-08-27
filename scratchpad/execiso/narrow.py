#!/usr/bin/env python3
"""Narrow the differ `multi` suite down to the op classes that actually diverge.

Usage: bisect.py TARGET_PORT ORACLE_PORT SEED CLASSES [TXMODES]
  CLASSES : comma list of body op classes to enable, e.g. mget,set,del
  TXMODES : comma list of transaction shapes, default exec,discard,abort,empty

Same generator shape as tests/differ.py's gen_multi, same pipelined byte-for-byte compare, but the
op mix is selectable so a divergence can be attributed to one command family instead of to "MULTI".
"""
import random
import socket
import sys

TP, OP, SEED = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
CLASSES = sys.argv[4].split(",") if len(sys.argv) > 4 else ["mget"]
TXMODES = sys.argv[5].split(",") if len(sys.argv) > 5 else ["exec", "discard", "abort", "empty"]
ROUNDS = int(sys.argv[6]) if len(sys.argv) > 6 else 700


def enc(argv):
    out = bytearray(b"*%d\r\n" % len(argv))
    for a in argv:
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
        return line
    if k == b"$":
        n = int(line[1:-2])
        if n == -1:
            return line
        return line + f.read(n + 2)
    if k == b"*":
        n = int(line[1:-2])
        if n == -1:
            return line
        return line + b"".join(read_reply(f) for _ in range(n))
    raise ValueError(line)


def conn(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


rng = random.Random(SEED)
keys = ["mx:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(38)))
        for i in range(24)]
listkeys, strkeys = keys[:6], keys[6:]
values = ["", "v", "hello", "42", "-7", "value-" + "y" * 90]
ops = []


def ks(n, pool=None):
    return [rng.choice(pool or strkeys) for _ in range(n)]


def pairs(n):
    out = []
    for key in ks(n):
        out += [key, rng.choice(values)]
    return out


MAKE = {
    "mget":     lambda: ["MGET"] + ks(rng.randrange(2, 8)),
    "mset":     lambda: ["MSET"] + pairs(rng.randrange(2, 6)),
    "exists":   lambda: ["EXISTS"] + ks(rng.randrange(2, 8)),
    "touch":    lambda: ["TOUCH"] + ks(rng.randrange(2, 8)),
    "del":      lambda: ["DEL"] + ks(rng.randrange(2, 6)),
    "set":      lambda: ["SET", rng.choice(strkeys), rng.choice(values)],
    "get":      lambda: ["GET", rng.choice(strkeys)],
    "incrby":   lambda: ["INCRBY", rng.choice(strkeys), str(rng.randrange(-5, 6))],
    "append":   lambda: ["APPEND", rng.choice(strkeys), rng.choice(values)],
    "strlen":   lambda: ["STRLEN", rng.choice(strkeys)],
    "msetnx":   lambda: ["MSETNX"] + pairs(rng.randrange(2, 5)),
    "rpush":    lambda: ["RPUSH", rng.choice(listkeys), rng.choice(values)],
    "lrange":   lambda: ["LRANGE", rng.choice(listkeys), "0", "-1"],
    "getrange": lambda: ["GETRANGE", rng.choice(strkeys), "0", str(rng.randrange(0, 5))],
}
for key in strkeys:
    ops.append(["SET", key, rng.choice(values)])
for key in listkeys:
    ops.append(["RPUSH", key, "seed"])


def body(n):
    return [MAKE[rng.choice(CLASSES)]() for _ in range(n)]


for _ in range(ROUNDS):
    mode = rng.choice(TXMODES)
    if mode == "discard":
        ops.append(["MULTI"]); ops += body(rng.randrange(1, 5)); ops.append(["DISCARD"])
    elif mode == "abort":
        ops.append(["MULTI"]); ops += body(rng.randrange(0, 3))
        ops.append(["GET"]); ops += body(rng.randrange(0, 3)); ops.append(["EXEC"])
    elif mode == "empty":
        ops.append(["MULTI"]); ops.append(["EXEC"])
    elif mode == "bare":
        ops += body(rng.randrange(1, 7))
    else:
        ops.append(["MULTI"]); ops += body(rng.randrange(1, 7)); ops.append(["EXEC"])
    ops += body(1)

ts, tf = conn(TP)
os_, of = conn(OP)
for s, f in ((ts, tf), (os_, of)):
    s.sendall(enc(["FLUSHALL"]))
    read_reply(f)
diffs = 0
queued = []
for i in range(0, len(ops), 64):
    chunk = ops[i:i + 64]
    payload = b"".join(enc(o) for o in chunk)
    ts.sendall(payload); os_.sendall(payload)
    for j, o in enumerate(chunk):
        name = o[0].upper()
        if name == "MULTI":
            queued = []
        elif name not in ("EXEC", "DISCARD"):
            queued.append(o)
        a, b = read_reply(tf), read_reply(of)
        if a != b:
            diffs += 1
            if diffs <= 3:
                print("  DIFF op %d %r\n    body:   %r\n    target: %r\n    oracle: %r"
                      % (i + j, o[:5], queued if name == "EXEC" else [],
                         a[:200], b[:200]), flush=True)
        if name in ("EXEC", "DISCARD"):
            queued = []
print("BISECT classes=%s txmodes=%s seed=%d: %d ops, %d diffs -> %s"
      % (",".join(CLASSES), ",".join(TXMODES), SEED, len(ops), diffs,
         "PASS" if not diffs else "FAIL"))
sys.exit(1 if diffs else 0)
