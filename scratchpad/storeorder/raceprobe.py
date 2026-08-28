#!/usr/bin/env python3
# raceprobe.py -- ORACLE-FREE program-order probe for cross-shard STORE destinations.
#
# One connection, ONE long pipelined write, repeating:
#     ZADD  src <n> m<n>            (plain write, src shard)
#     <STORE> dst src ...           (cross-shard store, dst shard)   -> :n
#     ZCARD dst                     (plain read,  dst shard)         -> must be :n
#     DEL   dst                     (plain write, dst shard)         -> must be :1
#     ZCARD dst                                                      -> must be :0
# Every reply is a function of the store's own reply, so no oracle is needed.  Any violation is
# an ordering or visibility defect between the store's destination install and the connection's
# later operations on that same key.
#
# usage: raceprobe.py <host> <port> <cycles> [seed] [--rounds N] [--kind K] [--quiet]
import socket, sys, random

HOST, PORT = sys.argv[1], int(sys.argv[2])
CYCLES = int(sys.argv[3]) if len(sys.argv) > 3 else 500
SEED = int(sys.argv[4]) if len(sys.argv) > 4 and not sys.argv[4].startswith("-") else 1
ROUNDS = int(sys.argv[sys.argv.index("--rounds") + 1]) if "--rounds" in sys.argv else 1
KIND = sys.argv[sys.argv.index("--kind") + 1] if "--kind" in sys.argv else "all"
QUIET = "--quiet" in sys.argv
NKEYS = int(sys.argv[sys.argv.index("--keys") + 1]) if "--keys" in sys.argv else 96


def enc(a):
    o = b"*%d\r\n" % len(a)
    for x in a:
        if isinstance(x, str): x = x.encode()
        o += b"$%d\r\n" % len(x) + x + b"\r\n"
    return o


def read_reply(f):
    line = f.readline()
    if not line: raise EOFError("eof")
    t = line[:1]
    if t in b"+-:,#(_": return line
    if t == b"$":
        n = int(line[1:-2]);  return line if n == -1 else line + f.read(n + 2)
    if t in b"*%~>":
        n = int(line[1:-2])
        if n == -1: return line
        if t == b"%": n *= 2
        out = line
        for _ in range(n): out += read_reply(f)
        return out
    raise RuntimeError("bad reply %r" % line)


def conn():
    s = socket.create_connection((HOST, PORT), timeout=60)
    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return s, s.makefile("rb")


KINDS = ["zrangestore", "zunionstore", "zinterstore", "zdiffstore", "sortstore",
         "geosearchstore", "copy", "sunionstore", "sinterstore", "sdiffstore",
         # UNBARRIERED members: RENAME/RENAMENX take the atomic_direct path at --atomic 1
         # (two_hop=false => ScatterState::barrier=false) and MSETNX takes the atomic_write
         # path, so both rely on the MVCC hazard gate instead of the connection barrier.
         "rename", "renamenx", "smove", "lmove", "rpoplpush", "bitop", "pfmerge", "msetnx"]


def cycle_ops(kind, src, src2, dst, n):
    """returns [(argv, expect_fn_name, expected_value), ...]"""
    if kind == "zrangestore":
        pre = [["ZADD", src, str(n), "m%d" % n]]
        store = ["ZRANGESTORE", dst, src, "0", "-1"]
        card = ["ZCARD", dst]
    elif kind == "zunionstore":
        pre = [["ZADD", src, str(n), "m%d" % n]]
        store = ["ZUNIONSTORE", dst, "2", src, src2]
        card = ["ZCARD", dst]
    elif kind == "zinterstore":
        pre = [["ZADD", src, str(n), "m%d" % n], ["ZADD", src2, str(n), "m%d" % n]]
        store = ["ZINTERSTORE", dst, "2", src, src2]
        card = ["ZCARD", dst]
    elif kind == "zdiffstore":
        pre = [["ZADD", src, str(n), "m%d" % n]]
        store = ["ZDIFFSTORE", dst, "2", src, src2]
        card = ["ZCARD", dst]
    elif kind == "sortstore":
        pre = [["RPUSH", src, str(n)]]
        store = ["SORT", src, "STORE", dst]
        card = ["LLEN", dst]
    elif kind == "geosearchstore":
        pre = [["GEOADD", src, "13.%03d" % (n % 900), "38.1", "p%d" % n]]
        store = ["GEOSEARCHSTORE", dst, src, "FROMLONLAT", "13.5", "38.1",
                 "BYRADIUS", "20000", "km", "ASC"]
        card = ["ZCARD", dst]
    elif kind == "copy":
        pre = [["ZADD", src, str(n), "m%d" % n]]
        store = ["COPY", src, dst, "REPLACE"]
        card = ["ZCARD", dst]
    elif kind == "sunionstore":
        pre = [["SADD", src, "m%d" % n]]
        store = ["SUNIONSTORE", dst, src, src2]
        card = ["SCARD", dst]
    elif kind == "sinterstore":
        pre = [["SADD", src, "m%d" % n], ["SADD", src2, "m%d" % n]]
        store = ["SINTERSTORE", dst, src, src2]
        card = ["SCARD", dst]
    elif kind == "sdiffstore":
        pre = [["SADD", src, "m%d" % n]]
        store = ["SDIFFSTORE", dst, src, src2]
        card = ["SCARD", dst]
    elif kind == "rename":
        pre = [["DEL", dst], ["ZADD", src, str(n), "m%d" % n]]
        store = ["RENAME", src, dst]
        card = ["ZCARD", dst]
    elif kind == "renamenx":
        pre = [["DEL", dst], ["ZADD", src, str(n), "m%d" % n]]
        store = ["RENAMENX", src, dst]
        card = ["ZCARD", dst]
    elif kind == "smove":
        pre = [["SADD", src, "m%d" % n]]
        store = ["SMOVE", src, dst, "m%d" % n]
        card = ["SCARD", dst]
    elif kind == "lmove":
        pre = [["RPUSH", src, "m%d" % n]]
        store = ["LMOVE", src, dst, "LEFT", "RIGHT"]
        card = ["LLEN", dst]
    elif kind == "rpoplpush":
        pre = [["RPUSH", src, "m%d" % n]]
        store = ["RPOPLPUSH", src, dst]
        card = ["LLEN", dst]
    elif kind == "bitop":
        pre = [["SET", src, "a" * n]]
        store = ["BITOP", "OR", dst, src, src2]
        card = ["STRLEN", dst]
    elif kind == "pfmerge":
        pre = [["PFADD", src, "m%d" % n]]
        store = ["PFMERGE", dst, src, src2]
        card = ["EXISTS", dst]
    elif kind == "msetnx":
        pre = [["DEL", dst, src2]]
        store = ["MSETNX", dst, "v%d" % n, src2, "w%d" % n]
        card = ["EXISTS", dst]
    else:
        pre = [["SADD", src, "m%d" % n]]
        store = ["SDIFFSTORE", dst, src, src2]
        card = ["SCARD", dst]
    return pre, store, card


def run(seed):
    rng = random.Random(seed)
    s, f = conn()
    s.sendall(enc(["FLUSHALL"])); read_reply(f)
    keys = ["rk%d" % i for i in range(NKEYS)]
    kinds = KINDS if KIND == "all" else [KIND]

    stream = []          # list of (argv, role, kindname)
    for c in range(CYCLES):
        kind = kinds[c % len(kinds)]
        src = "%s#s" % rng.choice(keys)
        src2 = "%s#t" % rng.choice(keys)
        dst = "%s#d" % rng.choice(keys)
        n = 1
        # build up the source across a few sub-cycles so the store count MOVES
        for n in range(1, 4):
            pre, store, card = cycle_ops(kind, src, src2, dst, n)
            for p in pre: stream.append((p, "pre", kind))
            stream.append((store, "store", kind))
            # COPY's reply is a 0/1 success flag, not a destination cardinality: the destination
            # must hold exactly what the source held, which is n members.
            # Kinds whose reply is a status/flag, not a destination cardinality: the destination
            # must instead hold a value that is a known function of n.
            CARD_N = {"copy": n, "rename": 1, "renamenx": 1, "smove": n, "lmove": n,
                      "rpoplpush": n, "bitop": n, "pfmerge": 1, "msetnx": 1}
            if kind in CARD_N:
                stream.append((card, "card_n", kind, CARD_N[kind]))
            else:
                stream.append((card, "card", kind, n))
        stream.append((["DEL", dst], "del", kind))
        stream.append((card, "card0", kind))
        stream.append((["DEL", src, src2], "cleanup", kind))

    stream = [t if len(t) == 4 else (t[0], t[1], t[2], None) for t in stream]
    payload = b"".join(enc(a) for a, _, _, _ in stream)
    s.sendall(payload)
    replies = [read_reply(f) for _ in stream]
    s.close()

    bad = 0
    per = {}
    examples = []
    last_store = None
    for i, (argv, role, kind, expected) in enumerate(stream):
        r = replies[i]
        if role == "store":
            last_store = r if r[:1] == b":" else None
        elif role == "card_n":
            if r != b":%d\r\n" % expected:
                bad += 1; per[kind] = per.get(kind, 0) + 1
                if len(examples) < 8:
                    examples.append("  op %d %-14s %r -> want :%d got %r" %
                                    (i, kind, argv, expected, r.strip()))
        elif role == "card" and last_store is not None:
            if r != last_store:
                bad += 1; per[kind] = per.get(kind, 0) + 1
                if len(examples) < 8:
                    examples.append("  op %d %-14s %r -> store=%r card=%r" %
                                    (i, kind, argv, last_store.strip(), r.strip()))
        elif role == "card0":
            if r != b":0\r\n":
                bad += 1; per[kind + "/afterdel"] = per.get(kind + "/afterdel", 0) + 1
                if len(examples) < 8:
                    examples.append("  op %d %-14s AFTER-DEL %r -> %r" % (i, kind, argv, r.strip()))
    return bad, per, examples, len(stream)


if __name__ == "__main__":
    badrounds = 0; agg = {}; total = 0
    for r in range(ROUNDS):
        bad, per, ex, n = run(SEED + r)
        total += bad
        if bad:
            badrounds += 1
            if not QUIET and badrounds <= 2:
                for e in ex: print(e)
        for k, v in per.items(): agg[k] = agg.get(k, 0) + v
    print("RACEPROBE port=%d cycles=%d kind=%s rounds=%d -> BAD ROUNDS %d/%d violations=%d %s" %
          (PORT, CYCLES, KIND, ROUNDS, badrounds, ROUNDS, total,
           " ".join("%s=%d" % kv for kv in sorted(agg.items()))))
    sys.exit(1 if badrounds else 0)
