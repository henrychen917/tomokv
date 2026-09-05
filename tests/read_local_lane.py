#!/usr/bin/env python3
"""Armed local-read LANE ADMISSION battery (P128.md).

Usage: read_local_lane.py HOST PORT      boot: --thread-mode 1s --read-local 1 --enable-debug-command yes

The fused thread's local-read lane holds kInboxSlots (1024) entries. A connection may pipeline up
to kRobWindow (64) ops, so a thread that has accepted more than 16 deep-pipelining connections can
be asked for more local reads in one rotation than its lane holds. The shipped rule is: the excess
is DEFERRED (the frame stays at rpos and is re-parsed by a later pass of the same thread, where it
is still served locally) and, while the lane is under pressure, the lane is divided among the
thread's active connections so that no connection can crowd out the ones the rotation parses last.
The former rule demoted the excess to the shard owner as an ordinary task; 7/8 of those tasks were
cross-thread, and they were the seed of the p128 / 2048-connection pure-read collapse.

Every check here is a counter delta over this battery's own traffic (vacuous-validation rule):
  geometry   the thinnest-guarded claim first: some thread owns > 1024/64 = 16 of our connections
             (SO_REUSEPORT hashes accepts, so we open 32 x threads and read the per-thread
             accepted counts back from DEBUG LBSIGNALS; the max is >= the mean by construction)
  lane full  read_local_defer_lane_full  > 0   the lane WAS oversubscribed -- otherwise every
                                                other check below would be vacuous
  no demote  read_local_fallback_lane_full == 0  capacity never creates an owner task
  fair share read_local_defer_quota      > 0   the pressure window armed and divided the lane
  local      read_local_hits delta >= 95% of the shared GETs (the rest may fall back for reasons
             unrelated to capacity, e.g. sequence churn from the RYOW writes below)
  order      every connection receives every reply, in order, with the expected value; the SET
             that follows the deferred GETs on the same connection and the GET behind it prove
             the frame order and read-your-own-write survive a deferral
  liveness   every round completes (a deferred frame must be re-parsed without an external wake)
"""
import sys
import time

import _lib

DEPTH = 64          # GETs per connection per round == kRobWindow: the per-connection lane pressure
CONNS_PER_THREAD = 32
ROUNDS = 12
ROUND_DEADLINE_S = 20.0
COUNTERS = ("read_local_hits", "read_local_fallbacks", "read_local_fallback_lane_full",
            "read_local_defer_lane_full", "read_local_defer_quota")


def counters(conn):
    table = _lib.info(conn, "stats")
    out = {}
    for key in COUNTERS:
        if key not in table:
            raise AssertionError("INFO stats has no %s; the battery cannot prove its mechanism"
                                 % key)
        out[key] = int(table[key])
    return out


def main():
    host, port = _lib.host_port()
    ctl = _lib.Conn(host, port)
    if _lib.thread_mode(ctl) != "1s":
        _lib.skip_all("lane admission exists only in fused (1s) mode")
    cfg = ctl.cmd("CONFIG", "GET", "read-local")
    if not (isinstance(cfg, list) and len(cfg) == 2 and cfg[1] == b"1"):
        _lib.skip_all("needs --read-local 1 (CONFIG GET read-local -> %r)" % (cfg,))
    rep = _lib.Report("read_local_lane")

    threads = _lib.lbsignals(ctl).threads
    nconns = CONNS_PER_THREAD * len(threads)
    shared = ["rl:lane:k%d" % i for i in range(DEPTH)]
    values = [b"v%d" % i for i in range(DEPTH)]
    for key, value in zip(shared, values):
        ctl.must("SET", key, value)
    before_clients = {t.tid: t.clients for t in threads}

    conns = [_lib.Conn(host, port, timeout=ROUND_DEADLINE_S, buffering=1 << 16)
             for _ in range(nconns)]
    for i, c in enumerate(conns):
        c.must("SET", "rl:lane:own:%d" % i, b"init")
    after = _lib.lbsignals(ctl).threads
    accepted = {t.tid: t.clients - before_clients.get(t.tid, 0) for t in after}
    top = max(accepted.values())
    rep.check("geometry: some thread owns > lane/window of our connections",
              top * DEPTH > 1024,
              "threads=%d conns=%d accepted per thread min=%d max=%d (x%d deep = %d > 1024)"
              % (len(threads), nconns, min(accepted.values()), top, DEPTH, top * DEPTH))

    base = counters(ctl)
    slow = 0.0
    order_ok = True
    order_detail = ""
    for r in range(ROUNDS):
        frames = []
        for i in range(nconns):
            payload = b"".join(_lib.encode("GET", k) for k in shared)
            payload += _lib.encode("SET", "rl:lane:own:%d" % i, "r%d" % r)
            payload += _lib.encode("GET", "rl:lane:own:%d" % i)
            frames.append(payload)
        t0 = time.monotonic()
        for c, payload in zip(conns, frames):
            c.sock.sendall(payload)
        for i, c in enumerate(conns):
            try:
                got = [c.read() for _ in range(DEPTH + 2)]
            except Exception as exc:   # a hang here is a deferred frame nobody re-parsed
                order_ok = False
                order_detail = "round %d conn %d: %r" % (r, i, exc)
                break
            want = values + [b"OK", b"r%d" % r]
            if got != want:
                order_ok = False
                bad = next(j for j in range(len(want)) if got[j] != want[j])
                order_detail = "round %d conn %d reply %d: got %r want %r" % (
                    r, i, bad, got[bad], want[bad])
                break
        slow = max(slow, time.monotonic() - t0)
        if not order_ok:
            break
    rep.check("order + RYOW across deferral: every reply, in order, expected value",
              order_ok, order_detail or "%d rounds x %d conns x %d frames" % (
                  ROUNDS, nconns, DEPTH + 2))
    rep.check("liveness: slowest round under %.0fs" % ROUND_DEADLINE_S,
              order_ok and slow < ROUND_DEADLINE_S, "slowest round %.3fs" % slow)

    now = counters(ctl)
    d = {k: now[k] - base[k] for k in COUNTERS}
    shared_gets = DEPTH * nconns * ROUNDS
    rep.check("lane oversubscribed: read_local_defer_lane_full > 0",
              d["read_local_defer_lane_full"] > 0, "delta=%d" % d["read_local_defer_lane_full"])
    rep.check("no capacity demotion: read_local_fallback_lane_full == 0",
              d["read_local_fallback_lane_full"] == 0,
              "delta=%d" % d["read_local_fallback_lane_full"])
    rep.check("fair share fired: read_local_defer_quota > 0",
              d["read_local_defer_quota"] > 0, "delta=%d" % d["read_local_defer_quota"])
    rep.check("shared GETs served locally (>= 95%%)",
              d["read_local_hits"] >= 0.95 * shared_gets,
              "hits=%d of %d shared GETs (%.2f%%); fallbacks=%d" % (
                  d["read_local_hits"], shared_gets, 100.0 * d["read_local_hits"] / shared_gets,
                  d["read_local_fallbacks"]))
    for c in conns:
        c.close()
    rep.finish()


if __name__ == "__main__":
    main()
