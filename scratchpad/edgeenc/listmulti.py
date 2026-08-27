"""Targeted hunt for NOTES-EXECISO.md defect (c): 'RPUSH of a large (96-byte) element inside
MULTI is lost, both atomic modes'.

Rebuilds the shape gen_multi deliberately does NOT generate: list mutations inside MULTI/EXEC over
a key set spread across the router, with the same 96-byte value gen_multi carries
("value-" + "y"*90).  Byte-compares against the vanilla oracle.

usage: p_listmulti.py TARGET_PORT ORACLE_PORT SEED [OPS]
"""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resp import Conn, encode

HOST = "127.0.0.1"
TP, OP_ = int(sys.argv[1]), int(sys.argv[2])
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1
NOPS = int(sys.argv[4]) if len(sys.argv) > 4 else 4000
rng = random.Random(SEED)

t, o = Conn(HOST, TP), Conn(HOST, OP_)
t.cmd("FLUSHALL"), o.cmd("FLUSHALL")

KEYS = ["lx:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(38)))
        for i in range(12)]
VALUES = ["", "v", "hello", "42", "value-" + "y" * 90,          # 96 bytes, the reported size
          "z" * 95, "z" * 96, "z" * 97, "w" * 63, "w" * 64, "w" * 192, "w" * 193]


def K():
    return rng.choice(KEYS)


def V():
    return rng.choice(VALUES)


def make():
    c = rng.randrange(16)
    if c in (0, 1, 2): return ["RPUSH", K()] + [V() for _ in range(rng.randrange(1, 4))]
    if c in (3, 4): return ["LPUSH", K()] + [V() for _ in range(rng.randrange(1, 4))]
    if c == 5: return ["LPOP", K()]
    if c == 6: return ["RPOP", K()]
    if c == 7: return ["LLEN", K()]
    if c == 8: return ["LRANGE", K(), str(rng.randrange(-6, 6)), str(rng.randrange(-6, 6))]
    if c == 9: return ["LINDEX", K(), str(rng.randrange(-6, 6))]
    if c == 10: return ["LSET", K(), str(rng.randrange(-4, 4)), V()]
    if c == 11: return ["LINSERT", K(), rng.choice(["BEFORE", "AFTER"]), V(), V()]
    if c == 12: return ["LREM", K(), str(rng.randrange(-2, 3)), V()]
    if c == 13: return ["LTRIM", K(), str(rng.randrange(-4, 4)), str(rng.randrange(-4, 4))]
    if c == 14: return ["RPUSHX", K(), V()]
    return ["DEL", K()]


ops = []
while len(ops) < NOPS:
    mode = rng.randrange(10)
    if mode < 6:
        ops.append(["MULTI"])
        for _ in range(rng.randrange(1, 8)):
            ops.append(make())
        ops.append(["EXEC"])
    elif mode == 6:
        ops.append(["MULTI"])
        for _ in range(rng.randrange(1, 4)):
            ops.append(make())
        ops.append(["DISCARD"])
    else:
        for _ in range(rng.randrange(1, 4)):
            ops.append(make())
    # settle: an ordered full read of every key, outside any transaction
    if rng.randrange(6) == 0:
        for k in KEYS:
            ops.append(["LRANGE", k, "0", "-1"])

ops = ops[:NOPS]
ops += [["LRANGE", k, "0", "-1"] for k in KEYS]
ops += [["LLEN", k] for k in KEYS]

BATCH = int(sys.argv[5]) if len(sys.argv) > 5 else 64
diffs = 0
for i in range(0, len(ops), BATCH):
    chunk = ops[i:i + BATCH]
    p = b"".join(encode(*x) for x in chunk)
    t.sock.sendall(p)
    o.sock.sendall(p)
    for j, x in enumerate(chunk):
        a, b = t.read(), o.read()
        if a != b:
            diffs += 1
            if diffs <= 8:
                print("DIFF op#%d %r\n   target=%s\n   oracle=%s"
                      % (i + j, [y[:20] for y in x[:5]], repr(a)[:200], repr(b)[:200]))
print("listmulti seed=%d ops=%d batch=%d diffs=%d -> %s"
      % (SEED, len(ops), BATCH, diffs, "PASS" if diffs == 0 else "FAIL"))
sys.exit(1 if diffs else 0)
