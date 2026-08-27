#!/usr/bin/env python3
"""Delta-debug the narrow.py `rpush,lrange` sequence down to a minimal losing transaction.

Usage: c_shrink.py TARGET_PORT ORACLE_PORT [SEED]

Oracle for "still broken": replay the candidate sequence from FLUSHALL on both servers, then
compare LRANGE 0 -1 of every list key.  Any difference = still reproduces.
"""
import random
import socket
import sys

TP, OP = int(sys.argv[1]), int(sys.argv[2])
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 1


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
        return line if n == -1 else line + f.read(n + 2)
    if k == b"*":
        n = int(line[1:-2])
        return line if n == -1 else line + b"".join(read_reply(f) for _ in range(n))
    raise ValueError(line)


def conn(port):
    s = socket.create_connection(("127.0.0.1", port), timeout=30)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


# ---- same generator as narrow.py, classes=rpush,lrange, txmode=exec -------------------------
rng = random.Random(SEED)
keys = ["mx:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(38)))
        for i in range(24)]
listkeys, strkeys = keys[:6], keys[6:]
values = ["", "v", "hello", "42", "-7", "value-" + "y" * 90]
ops = []
MAKE = {
    "rpush":  lambda: ["RPUSH", rng.choice(listkeys), rng.choice(values)],
    "lrange": lambda: ["LRANGE", rng.choice(listkeys), "0", "-1"],
}
CLASSES = ["rpush", "lrange"]
for key in strkeys:
    ops.append(["SET", key, rng.choice(values)])
for key in listkeys:
    ops.append(["RPUSH", key, "seed"])
for _ in range(700):
    ops.append(["MULTI"])
    ops += [MAKE[rng.choice(CLASSES)]() for _ in range(rng.randrange(1, 7))]
    ops.append(["EXEC"])
    ops += [MAKE[rng.choice(CLASSES)]()]
# ---------------------------------------------------------------------------------------------

ts, tf = conn(TP)
os_, of = conn(OP)


def replay(seq):
    """Run seq on both from a clean slate; return (target_lists, oracle_lists)."""
    res = []
    for s, f in ((ts, tf), (os_, of)):
        s.sendall(enc(["FLUSHALL"]))
        read_reply(f)
        for i in range(0, len(seq), 64):
            chunk = seq[i:i + 64]
            s.sendall(b"".join(enc(o) for o in chunk))
            for _ in chunk:
                read_reply(f)
        s.sendall(b"".join(enc(["LRANGE", k, "0", "-1"]) for k in listkeys))
        res.append([read_reply(f) for _ in listkeys])
    return res


def broken(seq):
    t, o = replay(seq)
    return t != o


def balanced(seq):
    """Reject sequences with an unmatched MULTI/EXEC."""
    depth = 0
    for o in seq:
        n = o[0].upper()
        if n == "MULTI":
            if depth:
                return False
            depth = 1
        elif n == "EXEC":
            if not depth:
                return False
            depth = 0
    return depth == 0


if not broken(ops):
    print("seed %d does not reproduce at all" % SEED)
    sys.exit(2)
print("full sequence (%d ops) reproduces; shrinking" % len(ops))

cur = ops
n = len(cur) // 2
while n >= 1:
    i = 0
    progress = False
    while i < len(cur):
        cand = cur[:i] + cur[i + n:]
        if cand and balanced(cand) and broken(cand):
            cur = cand
            progress = True
        else:
            i += n
    if not progress:
        n //= 2
    print("  ... %d ops (granularity %d)" % (len(cur), n), flush=True)

print("\nMINIMAL SEQUENCE (%d ops):" % len(cur))
used = set()
for o in cur:
    for a in o[1:]:
        if a in listkeys:
            used.add(a)
for o in cur:
    pretty = [("<L%d>" % listkeys.index(a)) if a in listkeys else a for a in o]
    print("   ", pretty)
t, o = replay(cur)
for i, k in enumerate(listkeys):
    if t[i] != o[i]:
        print("  L%d target=%r" % (i, t[i][:200]))
        print("  L%d oracle=%r" % (i, o[i][:200]))
