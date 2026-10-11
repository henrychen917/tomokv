#!/usr/bin/env python3
"""T4b: which single-key write commands keep a DISJOINT read local behind them (precise point
write) and which turn the connection conservative (every read parsed while the write is in flight
demotes). One armed connection, maxmemory 0, 1s and 2s; each case is one pipelined write
  <write on key t4b:w*>; GET t4b:z
and the GET's venue is read from read_local_* deltas. Replies are compared with Redis 7.4.
"""
import sys
from rl4lib import Server, Conn, rl_stats, delta, Report

rep = Report("T4b")
PORT = 25605

CASES = [
    ("SET", ("SET", "t4b:w1", "x")),
    ("SETEX", ("SETEX", "t4b:w2", "100", "x")),
    ("SETNX", ("SETNX", "t4b:w3", "x")),
    ("GETSET", ("GETSET", "t4b:w4", "x")),
    ("GETDEL", ("GETDEL", "t4b:w5")),
    ("GETEX", ("GETEX", "t4b:w6", "EX", "100")),
    ("APPEND", ("APPEND", "t4b:w7", "x")),
    ("INCR", ("INCR", "t4b:w8")),
    ("INCRBYFLOAT", ("INCRBYFLOAT", "t4b:w9", "1.5")),
    ("SETRANGE", ("SETRANGE", "t4b:w10", "0", "x")),
    ("DEL-1key", ("DEL", "t4b:w11")),
    ("UNLINK-1key", ("UNLINK", "t4b:w12")),
    ("EXPIRE", ("EXPIRE", "t4b:w13", "100")),
    ("PERSIST", ("PERSIST", "t4b:w14")),
    ("HSET", ("HSET", "t4b:h", "f", "v")),
    ("LPUSH", ("LPUSH", "t4b:l", "a")),
    ("SADD", ("SADD", "t4b:s", "a")),
    ("ZADD", ("ZADD", "t4b:zz", "1", "a")),
    ("SETBIT", ("SETBIT", "t4b:b", "7", "1")),
    ("PFADD", ("PFADD", "t4b:p", "a")),
    ("XADD", ("XADD", "t4b:x", "*", "f", "v")),
    ("MSET-1pair", ("MSET", "t4b:w15", "x")),
    ("MSETNX-1pair", ("MSETNX", "t4b:w16", "x")),
    ("RENAME", ("RENAME", "t4b:w1", "t4b:w17")),
    ("COPY", ("COPY", "t4b:w17", "t4b:w18")),
]


def run(label, args, kind):
    out = {}
    with Server(PORT, args, kind=kind, name="t4b-" + label):
        c = Conn(PORT)
        c.cmd("SET", "t4b:z", "zz")
        for i in range(1, 19):
            c.cmd("SET", "t4b:w%d" % i, "5")
        c.cmd("GET", "t4b:z")
        c.cmd("GET", "t4b:z")
        for name, write in CASES:
            c.cmd("PING")
            b = rl_stats(c) if kind == "tomo" else {}
            replies = c.pipeline([write, ("GET", "t4b:z")])
            a = rl_stats(c) if kind == "tomo" else {}
            if isinstance(replies[0], (bytes,)) and write[0] == "XADD":
                replies[0] = b"<id>"
            out[name] = (replies, delta(a, b) if kind == "tomo" else {})
        c.close()
    return out


redis = run("redis", [], "redis")
results = {"1s": run("1s", ["--thread-mode", "1s", "--read-local", "1"], "tomo"),
           "2s": run("2s", ["--thread-mode", "2s", "--read-local", "1"], "tomo")}
conservative = {}
for mode, res in results.items():
    for name, _ in CASES:
        rep.check("%s %s replies == redis" % (mode, name), res[name][0] == redis[name][0],
                  "tomo=%r redis=%r" % (res[name][0], redis[name][0]))
        d = res[name][1]
        local = d.get("read_local_hits", 0) == 1
        conservative.setdefault(name, []).append((mode, "LOCAL" if local else
                                                  "DEMOTED(%s)" % ",".join(
                                                      k[len("read_local_fallback_"):]
                                                      for k in d if k.startswith("read_local_fallback_"))))
for name, v in conservative.items():
    rep.note("disjoint GET behind %-14s" % name, v)
sys.exit(rep.finish())
