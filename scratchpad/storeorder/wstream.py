#!/usr/bin/env python3
# wstream.py -- long single-write pipelined stream over the cross-shard STORE family, diffed
# against the redis oracle AND checked oracle-free (store reply vs the very next read).
#
#   wstream.py <thost> <tport> <ohost> <oport> <seed> [ops] [--chunk N] [--rounds N] [--quiet]
#
# One chunk = one sendall().  --chunk 0 means "the entire stream in ONE write" (that is what the
# original H2 reducer did: 6404 ops in one write).
import socket, sys, random

TH, TP, OH, OP = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
SEED = int(sys.argv[5]) if len(sys.argv) > 5 else 1
NOPS = int(sys.argv[6]) if len(sys.argv) > 6 and not sys.argv[6].startswith("-") else 6000
CHUNK = 0
if "--chunk" in sys.argv: CHUNK = int(sys.argv[sys.argv.index("--chunk") + 1])
ROUNDS = 1
if "--rounds" in sys.argv: ROUNDS = int(sys.argv[sys.argv.index("--rounds") + 1])
QUIET = "--quiet" in sys.argv


def enc(args):
    o = b"*%d\r\n" % len(args)
    for a in args:
        if isinstance(a, str): a = a.encode()
        o += b"$%d\r\n" % len(a) + a + b"\r\n"
    return o


def read_reply(f):
    line = f.readline()
    if not line: raise EOFError("eof")
    t = line[:1]
    if t in b"+-:,#(": return line
    if t == b"$":
        n = int(line[1:-2])
        return line if n == -1 else line + f.read(n + 2)
    if t in b"*%~>":
        n = int(line[1:-2])
        if n == -1: return line
        if t == b"%": n *= 2
        out = line
        for _ in range(n): out += read_reply(f)
        return out
    if t == b"_": return line
    raise RuntimeError("bad reply %r" % line)


def conn(h, p):
    s = socket.create_connection((h, p), timeout=60)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


ZS = ["db:z%d" % i for i in range(4)]     # zset sources
SS = ["db:s%d" % i for i in range(4)]     # set sources
LS = ["db:l%d" % i for i in range(3)]     # list sources
GS = ["db:g%d" % i for i in range(2)]     # geo sources
BS = ["db:b%d" % i for i in range(3)]     # string sources (BITOP)
DS = ["db:d%d" % i for i in range(8)]     # STORE destinations


def setup_ops():
    ops = []
    for i, k in enumerate(ZS):
        ops.append(["ZADD", k, "1", "a", "2", "b", "3", "c", str(16 + i), "d"])
    for i, k in enumerate(SS):
        ops.append(["SADD", k, "a", "b", "c", chr(ord("d") + i)])
    for k in LS:
        ops.append(["RPUSH", k, "3", "1", "2", "10"])
    for k in GS:
        ops.append(["GEOADD", k, "13.361389", "38.115556", "palermo",
                    "15.087269", "37.502669", "catania"])
    for i, k in enumerate(BS):
        ops.append(["SET", k, "abcdefgh"[i:] or "xy"])
    return ops


def store_op(rng, dst):
    """Return (argv, read_argv, kind) for a cross-shard store into dst."""
    which = rng.randrange(12)
    if which == 0:
        return (["ZRANGESTORE", dst, rng.choice(ZS), "0", "-1"],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "zrangestore")
    if which == 1:
        return (["ZRANGESTORE", dst, rng.choice(ZS), "(1", "+inf", "BYSCORE"],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "zrangestore")
    if which == 2:
        a, b = rng.choice(ZS), rng.choice(ZS)
        return (["ZUNIONSTORE", dst, "2", a, b],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "zunionstore")
    if which == 3:
        a, b = rng.choice(ZS), rng.choice(ZS)
        return (["ZINTERSTORE", dst, "2", a, b],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "zinterstore")
    if which == 4:
        a, b = rng.choice(ZS), rng.choice(ZS)
        return (["ZDIFFSTORE", dst, "2", a, b],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "zdiffstore")
    if which == 5:
        a, b = rng.choice(SS), rng.choice(SS)
        return (["SUNIONSTORE", dst, a, b], ["SMEMBERS", dst], "sunionstore")
    if which == 6:
        a, b = rng.choice(SS), rng.choice(SS)
        return (["SINTERSTORE", dst, a, b], ["SMEMBERS", dst], "sinterstore")
    if which == 7:
        a, b = rng.choice(SS), rng.choice(SS)
        return (["SDIFFSTORE", dst, a, b], ["SMEMBERS", dst], "sdiffstore")
    if which == 8:
        return (["SORT", rng.choice(LS), "STORE", dst], ["LRANGE", dst, "0", "-1"], "sortstore")
    if which == 9:
        return (["GEOSEARCHSTORE", dst, rng.choice(GS), "FROMLONLAT", "15", "37",
                 "BYRADIUS", "200", "km", "ASC"],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "geosearchstore")
    if which == 10:
        return (["COPY", rng.choice(ZS), dst, "REPLACE"],
                ["ZRANGE", dst, "0", "-1", "WITHSCORES"], "copy")
    return (["BITOP", "AND", dst, rng.choice(BS), rng.choice(BS)], ["GET", dst], "bitop")


def build_stream(rng, nops):
    ops = list(setup_ops())
    while len(ops) < nops:
        dst = rng.choice(DS)
        store, read, kind = store_op(rng, dst)
        ops.append(store)
        ops.append(read)
        if rng.randrange(4) == 0:
            ops.append(["EXISTS", dst])
        ops.append(["DEL", dst])
        # noise: unrelated keys, keeps many owners busy and lengthens the window
        for _ in range(rng.randrange(3)):
            k = rng.choice(ZS + SS + LS + BS)
            ops.append(rng.choice([["TYPE", k], ["EXISTS", k], ["OBJECT", "REFCOUNT", k],
                                   ["TTL", k], ["STRLEN", rng.choice(BS)]]))
    return ops


def norm(cmd, r):
    # SMEMBERS order is implementation-defined on both servers: compare as a SET.
    if cmd == "SMEMBERS" and r[:1] == b"*":
        parts = r.split(b"\r\n")
        return b"|".join(sorted(p for p in parts[1:] if p and not p.startswith(b"$")))
    return r


def run(seed, verbose):
    rng = random.Random(seed)
    ops = build_stream(rng, NOPS)
    ts, tf = conn(TH, TP)
    os_, of = conn(OH, OP)
    for cs, cf in ((ts, tf), (os_, of)):
        cs.sendall(enc(["FLUSHALL"]))
        if read_reply(cf)[:1] != b"+": raise RuntimeError("flushall")
    step = CHUNK if CHUNK else len(ops)
    treplies = []
    oreplies = []
    for i in range(0, len(ops), step):
        chunk = ops[i:i + step]
        payload = b"".join(enc(o) for o in chunk)
        ts.sendall(payload); os_.sendall(payload)
        for _ in chunk:
            treplies.append(read_reply(tf))
        for _ in chunk:
            oreplies.append(read_reply(of))
    # ORACLE-FREE invariant, computed on RAW replies before normalization: a store that answered
    # :N>0 followed immediately by a read of the same destination that saw nothing.
    ackloss = 0
    for i, o in enumerate(ops):
        if o[0].upper() in ("ZRANGESTORE", "ZUNIONSTORE", "ZINTERSTORE", "ZDIFFSTORE",
                            "SUNIONSTORE", "SINTERSTORE", "SDIFFSTORE", "SORT",
                            "GEOSEARCHSTORE"):
            if treplies[i][:1] != b":": continue
            if int(treplies[i][1:-2]) > 0 and treplies[i + 1][:2] == b"*0": ackloss += 1
    diffs = 0
    shown = []
    for i, o in enumerate(ops):
        treplies[i] = norm(o[0].upper(), treplies[i])
        oreplies[i] = norm(o[0].upper(), oreplies[i])
        if treplies[i] != oreplies[i]:
            diffs += 1
            if len(shown) < 10:
                shown.append("  DIFF op %d %r\n    target: %r\n    oracle: %r" %
                             (i, o[:5], treplies[i][:120], oreplies[i][:120]))
    ts.close(); os_.close()
    return diffs, shown, len(ops), ackloss


if __name__ == "__main__":
    bad = 0
    tot = 0
    for r in range(ROUNDS):
        d, shown, n, ack = run(SEED + r, not QUIET)
        tot += d
        if d: bad += 1
        if d and not QUIET and bad <= 2:
            for s in shown: print(s)
        if not QUIET:
            print("  round %d: %d ops, %d diffs, ackloss=%d" % (r, n, d, ack))
    print("WSTREAM seed=%d ops=%d chunk=%s rounds=%d -> DIVERGED %d/%d (total diffs %d)" %
          (SEED, NOPS, CHUNK or "ALL", ROUNDS, bad, ROUNDS, tot))
    sys.exit(1 if bad else 0)
