#!/usr/bin/env python3
"""T2: what the lane does with misses, wrong types and expired keys -- and whether the wire and the
Redis-visible counters match Redis 7.4.

For each server (tomo 1s rl=1, tomo 2s rl=1, tomo 1s rl=0, Redis 7.4 oracle):
  A  GET of a missing key                          -> reply, keyspace_hits/misses delta
  B  MGET of 1 present + 2 missing keys            -> reply, keyspace deltas
  C  GET of a list key (WRONGTYPE)                 -> reply
  D  MGET over a list key + string key             -> reply
  E  GET of an expired key (lazy expiry)           -> reply, expired_keys, keyspace deltas
  F  MGET with one expired key                     -> reply, deltas
On tomo rl=1 also record the read_local_* counter deltas per scenario, which names the venue
(lane hit, or fallback reason).
"""
import sys
import time
from rl4lib import Server, Conn, info, rl_stats, delta, Report

rep = Report("T2")
PORT = 25602
KS = ("keyspace_hits", "keyspace_misses", "expired_keys")


def ks(c):
    st = info(c, "stats")
    return {k: int(st[k]) for k in KS}


def scenario(c, label, fn, armed):
    # the connection is armed and quiet before every scenario
    c.cmd("PING")
    b_ks, b_rl = ks(c), (rl_stats(c) if armed else {})
    reply = fn(c)
    a_ks, a_rl = ks(c), (rl_stats(c) if armed else {})
    return reply, delta(a_ks, b_ks, KS), (delta(a_rl, b_rl) if armed else {})


def run(server_label, args, kind="tomo"):
    results = {}
    with Server(PORT, args, kind=kind, name="t2-" + server_label):
        c = Conn(PORT)
        armed = kind == "tomo" and "--read-local" in args and args[args.index("--read-local") + 1] == "1"
        c.cmd("SET", "t2:s", "val")
        c.cmd("RPUSH", "t2:l", "a")
        c.cmd("GET", "t2:s")
        results["A get-miss"] = scenario(c, "A", lambda c: c.cmd("GET", "t2:missing"), armed)
        results["B mget-1hit-2miss"] = scenario(
            c, "B", lambda c: c.cmd("MGET", "t2:s", "t2:m1", "t2:m2"), armed)
        results["C get-wrongtype"] = scenario(c, "C", lambda c: c.cmd("GET", "t2:l"), armed)
        results["D mget-wrongtype"] = scenario(c, "D", lambda c: c.cmd("MGET", "t2:l", "t2:s"), armed)
        r = c.cmd("DEBUG", "SET-ACTIVE-EXPIRE", "0")
        assert r == b"OK", r
        c.cmd("SET", "t2:e1", "x", "PX", "40")
        c.cmd("SET", "t2:e2", "y", "PX", "40")
        time.sleep(0.25)
        results["E get-expired"] = scenario(c, "E", lambda c: c.cmd("GET", "t2:e1"), armed)
        results["F mget-expired"] = scenario(c, "F", lambda c: c.cmd("MGET", "t2:s", "t2:e2"), armed)
        c.close()
    return results


servers = [
    ("redis74", ["--enable-debug-command", "yes"], "redis"),
    ("tomo-1s-rl1", ["--thread-mode", "1s", "--read-local", "1", "--enable-debug-command", "yes"], "tomo"),
    ("tomo-2s-rl1", ["--thread-mode", "2s", "--read-local", "1", "--enable-debug-command", "yes"], "tomo"),
    ("tomo-1s-rl0", ["--thread-mode", "1s", "--read-local", "0", "--enable-debug-command", "yes"], "tomo"),
]
all_res = {}
for label, args, kind in servers:
    all_res[label] = run(label, args, kind)
    for scen, (reply, ksd, rld) in all_res[label].items():
        rep.note("%s %s" % (label, scen), "reply=%r ks=%r rl=%r" % (reply, ksd, rld))

oracle = all_res["redis74"]
for label in ("tomo-1s-rl1", "tomo-2s-rl1", "tomo-1s-rl0"):
    for scen in oracle:
        r_reply, r_ks, _ = oracle[scen]
        t_reply, t_ks, t_rl = all_res[label][scen]
        rep.check("%s %s reply == redis" % (label, scen), t_reply == r_reply,
                  "tomo=%r redis=%r" % (t_reply, r_reply))
        rep.check("%s %s keyspace/expired deltas == redis" % (label, scen), t_ks == r_ks,
                  "tomo=%r redis=%r" % (t_ks, r_ks))

# Venue facts (the finding under test): GET miss demotes; MGET miss is served on the lane;
# an expired key (active expiry disabled, so the key is still resident) demotes GET and MGET.
for label in ("tomo-1s-rl1", "tomo-2s-rl1"):
    _, _, rl = all_res[label]["A get-miss"]
    rep.check("%s GET miss is NOT a lane hit (fallback_missing)" % label,
              rl.get("read_local_hits", 0) == 0 and rl.get("read_local_fallback_missing", 0) == 1, rl)
    _, _, rl = all_res[label]["B mget-1hit-2miss"]
    rep.check("%s MGET with misses IS a lane hit" % label,
              rl.get("read_local_mget_local_hits", 0) == 1 and rl.get("read_local_keyspace_misses", 0) == 2, rl)
for label in ("tomo-1s-rl1", "tomo-2s-rl1"):
    _, _, rl = all_res[label]["E get-expired"]
    rep.check("%s GET of a resident expired key -> fallback_expired" % label,
              rl.get("read_local_fallback_expired", 0) == 1, rl)
    _, _, rl = all_res[label]["F mget-expired"]
    rep.check("%s MGET with a resident expired key -> mget_fallback_expired" % label,
              rl.get("read_local_mget_fallback_expired", 0) == 1, rl)
sys.exit(rep.finish())
