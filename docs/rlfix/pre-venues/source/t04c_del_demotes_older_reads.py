#!/usr/bin/env python3
"""T4c: a single-key DEL/UNLINK is a BROAD write for the read-local parser (registry last_key -1),
so it demotes (a) every younger read parsed while it is in flight [T4b] and (b) every OLDER local
read of the same connection that is still pending when the DEL is parsed. Compare SET (precise).

One armed connection, 1s and 2s; each case is one pipelined write:
  GET z1; GET z2; GET z3; <write a>; GET z4
and the venue of all four GETs is read from read_local_* deltas. Replies vs Redis 7.4.
"""
import sys
from rl4lib import Server, Conn, rl_stats, delta, Report

rep = Report("T4c")
PORT = 25606
WRITES = [("SET", ("SET", "t4c:a", "x")), ("DEL-1key", ("DEL", "t4c:a")),
          ("UNLINK-1key", ("UNLINK", "t4c:a")), ("DEL-2keys", ("DEL", "t4c:a", "t4c:b"))]


def run(label, args, kind):
    out = {}
    with Server(PORT, args, kind=kind, name="t4c-" + label):
        c = Conn(PORT)
        for k in ("t4c:z1", "t4c:z2", "t4c:z3", "t4c:z4"):
            c.cmd("SET", k, k)
        c.cmd("GET", "t4c:z1"); c.cmd("GET", "t4c:z1")
        for name, w in WRITES:
            c.cmd("SET", "t4c:a", "1"); c.cmd("SET", "t4c:b", "1"); c.cmd("GET", "t4c:z1")
            c.cmd("PING")
            b = rl_stats(c) if kind == "tomo" else {}
            cmds = [("GET", "t4c:z1"), ("GET", "t4c:z2"), ("GET", "t4c:z3"), w, ("GET", "t4c:z4")]
            replies = c.pipeline(cmds)
            a = rl_stats(c) if kind == "tomo" else {}
            out[name] = (replies, delta(a, b) if kind == "tomo" else {})
        c.close()
    return out


redis = run("redis", [], "redis")
for mode, args in (("1s", ["--thread-mode", "1s", "--read-local", "1"]),
                   ("2s", ["--thread-mode", "2s", "--read-local", "1"])):
    res = run(mode, args, "tomo")
    for name, _ in WRITES:
        rep.check("%s %s replies == redis" % (mode, name), res[name][0] == redis[name][0],
                  "tomo=%r redis=%r" % (res[name][0], redis[name][0]))
        d = res[name][1]
        rep.note("%s %-11s 4 GETs: local=%d demoted=%d" % (
            mode, name, d.get("read_local_hits", 0), d.get("read_local_fallbacks", 0)), d)
    rep.check("%s SET a: all 4 disjoint GETs stay local" % mode,
              res["SET"][1].get("read_local_hits", 0) == 4, res["SET"][1])
    dd = res["DEL-1key"][1]
    rep.check("%s DEL a (one key): disjoint GETs demoted (older pending + younger)" % mode,
              dd.get("read_local_fallbacks", 0) >= 1, dd)
sys.exit(rep.finish())
