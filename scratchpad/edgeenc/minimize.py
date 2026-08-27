"""Delta-minimize the list-in-MULTI divergence down to a reproducer a human can read.

Generates the same stream as p_listmulti.py, truncates at the first divergence, then greedily
removes operations while the divergence survives.  Each candidate is replayed from FLUSHALL on
both servers, so the result is a self-contained script.

usage: p_minimize.py TARGET_PORT ORACLE_PORT SEED [OPS] [BATCH]
"""
import os, sys, random
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from resp import Conn, encode

HOST = "127.0.0.1"
TP, OP_ = int(sys.argv[1]), int(sys.argv[2])
SEED = int(sys.argv[3]) if len(sys.argv) > 3 else 4
NOPS = int(sys.argv[4]) if len(sys.argv) > 4 else 4000
BATCH = int(sys.argv[5]) if len(sys.argv) > 5 else 64
rng = random.Random(SEED)

t, o = Conn(HOST, TP), Conn(HOST, OP_)

KEYS = ["lx:%02d:%s" % (i, "".join(rng.choice("abcdef0123456789") for _ in range(38)))
        for i in range(12)]
VALUES = ["", "v", "hello", "42", "value-" + "y" * 90,
          "z" * 95, "z" * 96, "z" * 97, "w" * 63, "w" * 64, "w" * 192, "w" * 193]
K = lambda: rng.choice(KEYS)
V = lambda: rng.choice(VALUES)


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
ops = ops[:NOPS]


def balanced(seq):
    """Keep MULTI/EXEC nesting well-formed after deletions."""
    depth = 0
    for x in seq:
        head = x[0].upper()
        if head == "MULTI":
            if depth:
                return False
            depth = 1
        elif head in ("EXEC", "DISCARD"):
            if not depth:
                return False
            depth = 0
    return depth == 0


def replay(seq):
    """Run seq on FRESH connections from a clean slate on both; index of first diff or None.

    Fresh connections on purpose: a truncated replay can stop inside an open MULTI, and a reused
    connection would then answer +QUEUED to the next probe -- which is how an earlier version of
    this minimizer produced a three-command 'reproducer' that was really a desynchronized socket.
    """
    tt, oo = Conn(HOST, TP), Conn(HOST, OP_)
    try:
        # LIVENESS GUARD: a dead server would otherwise be minimized into a fake reproducer.
        for c, name in ((tt, "target"), (oo, "oracle")):
            if c.cmd("PING") != b"PONG":
                raise SystemExit("%s is not answering PING -- results from here are void" % name)
            c.cmd("FLUSHALL")
        probe = seq + [["LRANGE", k, "0", "-1"] for k in KEYS] + [["LLEN", k] for k in KEYS]
        for i in range(0, len(probe), BATCH):
            chunk = probe[i:i + BATCH]
            p = b"".join(encode(*x) for x in chunk)
            tt.sock.sendall(p)
            oo.sock.sendall(p)
            for j, x in enumerate(chunk):
                a, b = tt.read(), oo.read()
                if a != b:
                    return i + j
        return None
    finally:
        tt.close(); oo.close()


REPEATS = 6


def diverges(seq):
    """The defect is a race: a candidate counts as still-failing if ANY of REPEATS replays
    diverges. A single-shot check greedily deletes the very operations that widen the window."""
    for _ in range(REPEATS):
        idx = replay(seq)
        if idx is not None:
            return idx
    return None


first = replay(ops)
print("first divergence at op#%s of %d" % (first, len(ops)))
if first is None:
    sys.exit("no divergence for this seed")

cand = ops[:first + 1]
if not balanced(cand):
    # extend to the end of the enclosing transaction
    k = first + 1
    while k < len(ops) and not balanced(ops[:k]):
        k += 1
    cand = ops[:k]
print("truncated to %d ops" % len(cand))
assert diverges(cand) is not None, "truncation lost the divergence"

# greedy shrink: try removing chunks, largest first
size = max(1, len(cand) // 2)
while size >= 1:
    i = 0
    while i < len(cand):
        trial = cand[:i] + cand[i + size:]
        if trial and balanced(trial) and diverges(trial) is not None:
            cand = trial
        else:
            i += size
    if size == 1:
        break
    size = max(1, size // 2)

print("MINIMAL: %d ops" % len(cand))
names = {}
for x in cand:
    if len(x) > 1 and x[0].upper() not in ("MULTI", "EXEC", "DISCARD"):
        names.setdefault(x[1], "k%d" % len(names))
for x in cand:
    pretty = []
    for i, y in enumerate(x):
        if i == 1 and y in names:
            pretty.append(names[y])
        elif len(y) > 24:
            pretty.append("<%s x%d>" % (y[0], len(y)))
        else:
            pretty.append(y)
    print("   " + " ".join(pretty))
hits = sum(1 for _ in range(20) if replay(cand) is not None)
print("minimal script diverges in %d/20 replays (+%d trailing probes per replay)" % (hits, 2 * len(KEYS)))
