#!/usr/bin/env python3
"""Breadth sweep for defect (d): does ANY cross-shard multi-key command answer differently inside
MULTI than it does bare?  Runs each shape twice on a clean slate -- once bare, once wrapped in
MULTI/EXEC -- and compares the reply and the resulting keyspace.

Usage: breadth.py PORT
"""
import socket
import sys

TP = int(sys.argv[1])


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


s = socket.create_connection(("127.0.0.1", TP), timeout=30)
s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
f = s.makefile("rb")


def cmd(*argv):
    s.sendall(enc(list(argv)))
    return read_reply(f)


def shard(k):
    return int(cmd("DEBUG", "SHARD", k)[1:-2])


# two keys guaranteed on different shards
pool = {}
i = 0
while len(pool) < 3 and i < 2000:
    k = "bk:%04d" % i
    pool.setdefault(shard(k), k)
    i += 1
A, B, C = [pool[x] for x in sorted(pool)[:3]]
print("A=%s(sh %d) B=%s(sh %d) C=%s(sh %d)" % (A, shard(A), B, shard(B), C, shard(C)))

STR = [["SET", A, "ohmytext"], ["SET", B, "mynewtext"], ["SET", C, "z"]]
SET = [["SADD", A, "a", "b", "c"], ["SADD", B, "b", "c", "d"], ["SADD", C, "q"]]
ZSET = [["ZADD", A, "1", "a", "2", "b"], ["ZADD", B, "3", "b", "4", "d"], ["ZADD", C, "5", "q"]]
LIST = [["RPUSH", A, "a", "b", "c"], ["RPUSH", B, "x"], ["RPUSH", C, "q"]]
HLL = [["PFADD", A, "a", "b"], ["PFADD", B, "c", "d"], ["PFADD", C, "e"]]

CASES = [
    ("MGET", STR, ["MGET", A, B]),
    ("MSET", [], ["MSET", A, "1", B, "2"]),
    ("MSETNX", [], ["MSETNX", A, "1", B, "2"]),
    ("DEL", STR, ["DEL", A, B]),
    ("UNLINK", STR, ["UNLINK", A, B]),
    ("EXISTS", STR, ["EXISTS", A, B]),
    ("TOUCH", STR, ["TOUCH", A, B]),
    ("LCS", STR, ["LCS", A, B]),
    ("LCS LEN", STR, ["LCS", A, B, "LEN"]),
    ("LCS IDX", STR, ["LCS", A, B, "IDX", "MINMATCHLEN", "4", "WITHMATCHLEN"]),
    ("BITOP", STR, ["BITOP", "AND", C, A, B]),
    ("COPY", STR, ["COPY", A, B, "REPLACE"]),
    ("RENAME", STR, ["RENAME", A, B]),
    ("RENAMENX", STR, ["RENAMENX", A, B]),
    ("SINTER", SET, ["SINTER", A, B]),
    ("SUNION", SET, ["SUNION", A, B]),
    ("SDIFF", SET, ["SDIFF", A, B]),
    ("SINTERCARD", SET, ["SINTERCARD", "2", A, B]),
    ("SINTERSTORE", SET, ["SINTERSTORE", C, A, B]),
    ("SUNIONSTORE", SET, ["SUNIONSTORE", C, A, B]),
    ("SDIFFSTORE", SET, ["SDIFFSTORE", C, A, B]),
    ("SMOVE", SET, ["SMOVE", A, B, "a"]),
    ("ZINTER", ZSET, ["ZINTER", "2", A, B]),
    ("ZUNION", ZSET, ["ZUNION", "2", A, B]),
    ("ZDIFF", ZSET, ["ZDIFF", "2", A, B]),
    ("ZINTERCARD", ZSET, ["ZINTERCARD", "2", A, B]),
    ("ZINTERSTORE", ZSET, ["ZINTERSTORE", C, "2", A, B]),
    ("ZUNIONSTORE", ZSET, ["ZUNIONSTORE", C, "2", A, B]),
    ("ZDIFFSTORE", ZSET, ["ZDIFFSTORE", C, "2", A, B]),
    ("ZRANGESTORE", ZSET, ["ZRANGESTORE", C, A, "0", "-1"]),
    ("ZMPOP", ZSET, ["ZMPOP", "2", A, B, "MIN"]),
    ("LMPOP", LIST, ["LMPOP", "2", A, B, "LEFT"]),
    ("LMOVE", LIST, ["LMOVE", A, B, "LEFT", "RIGHT"]),
    ("RPOPLPUSH", LIST, ["RPOPLPUSH", A, B]),
    ("PFCOUNT", HLL, ["PFCOUNT", A, B]),
    ("PFMERGE", HLL, ["PFMERGE", C, A, B]),
    ("SORT", LIST, ["SORT", A, "ALPHA", "STORE", C]),
    ("SORT_RO", LIST, ["SORT_RO", A, "ALPHA"]),
    ("KEYS", STR, ["KEYS", "bk:*"]),
    # conditional-failure shapes: the answer is a normal 0, not an error
    ("RENAMENX-nx-fail", STR, ["RENAMENX", A, B]),
    ("RENAMENX-nx-ok", [["SET", A, "v"]], ["RENAMENX", A, B]),
    ("COPY-nx-fail", STR, ["COPY", A, B]),
    ("COPY-nx-ok", [["SET", A, "v"]], ["COPY", A, B]),
    ("SMOVE-miss", SET, ["SMOVE", A, B, "zzz"]),
    ("MSETNX-fail", STR, ["MSETNX", A, "1", B, "2"]),
    ("GEOSEARCHSTORE", [["GEOADD", A, "13.361389", "38.115556", "p"]],
     ["GEOSEARCHSTORE", C, A, "FROMLONLAT", "13.361389", "38.115556", "BYRADIUS", "200", "km",
      "ASC"]),
]

bad = 0
for name, setup, body in CASES:
    results = []
    for wrapped in (False, True):
        cmd("FLUSHALL")
        for c in setup:
            cmd(*c)
        if wrapped:
            cmd("MULTI")
            cmd(*body)
            r = cmd("EXEC")
        else:
            r = cmd(*body)
        after = [cmd("TYPE", k) + cmd("DEBUG", "SHARD", k) for k in (A, B, C)]
        # normalise: EXEC wraps the reply in a one-element array
        results.append((r, after))
    bare, wrap = results
    wrap_inner = wrap[0]
    same_state = bare[1] == wrap[1]
    err = b"internal cross-shard completion error" in wrap_inner
    # strip the EXEC array header for the reply comparison
    stripped = wrap_inner.split(b"\r\n", 1)[1] if wrap_inner.startswith(b"*1\r\n") else wrap_inner
    same_reply = stripped == bare[0]
    if err or not same_state or not same_reply:
        bad += 1
        print("DIFF %-16s err=%s reply_same=%s state_same=%s" % (name, err, same_reply, same_state))
        print("      bare = %r" % (bare[0][:140],))
        print("      exec = %r" % (wrap_inner[:140],))
        if not same_state:
            print("      bare state = %r" % (bare[1],))
            print("      exec state = %r" % (wrap[1],))
    else:
        print("ok   %-16s %r" % (name, bare[0][:60]))

print("\n%d/%d shapes differ inside MULTI" % (bad, len(CASES)))
sys.exit(1 if bad else 0)
