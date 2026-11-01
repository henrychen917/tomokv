#!/usr/bin/env python3
"""XS-NOTIFY-1: a cross-owner script that writes its two declared keys must publish keyspace
events and CLIENT TRACKING invalidations, like a single-owner script and like Redis.

Per attempt and per shape (cross-owner pair, same-shard pair, same-owner/two-shard pair):
  T (RESP3, CLIENT TRACKING ON) reads both keys (enrols them);
  S (RESP2) is PSUBSCRIBEd to __keyspace@0__:* and __keyevent@0__:*;
  W runs EVAL "set KEYS[1]; set KEYS[2]" 2 k1 k2 v.
Collected for up to 1 s: invalidations on T, events on S.
A HIT for the cross-owner shape = DEBUG SHARDS shows different owners before AND after the
attempt and script_crossshard_activations advanced by exactly one.
"""
import argparse
import json
import os
import sys
import time


from srv import Server, shards_of, geometry_text  # noqa: E402
from resp import info_dict, b2s, Push  # noqa: E402

SCRIPT = "redis.call('set', KEYS[1], ARGV[1]); redis.call('set', KEYS[2], ARGV[1]); return 1"


def pick_keys(c, is_redis):
    if is_redis:
        return {"cross_owner": ("xs:a", "xs:b"), "same_shard": ("ss:a", "ss:b"),
                "same_owner_2shards": ("so:a", "so:b")}
    names = ["k%d" % i for i in range(4096)]
    geo = []
    for i in range(0, len(names), 256):
        geo += shards_of(c, names[i:i + 256])
    m = dict(zip(names, geo))
    cross = same_shard = same_owner = None
    for a in names:
        for b in names[:400]:
            if a == b:
                continue
            (sa, oa), (sb, ob) = m[a], m[b]
            if cross is None and oa != ob:
                cross = (a, b)
            if same_shard is None and sa == sb:
                same_shard = (a, b)
            if same_owner is None and oa == ob and sa != sb:
                same_owner = (a, b)
        if cross and same_shard and same_owner:
            break
    out = {"cross_owner": cross, "same_shard": same_shard}
    if same_owner:
        out["same_owner_2shards"] = same_owner
    return out


def stat(c, field):
    return int(info_dict(c).get(field, "0"))


def run(geom, port, attempts, out, force=False):
    is_redis = geom == "redis"
    srv = Server(geom, port, tag="t1")
    srv.start()
    res = {"item": "XS-NOTIFY-1", "geometry": geom, "geometry_text": geometry_text(geom),
           "argv": " ".join(a if a else "''" for a in srv.argv), "shapes": {}}
    try:
        admin = srv.conn(name="admin")
        if force and not is_redis:
            assert admin.call('DEBUG', 'SCRIPT-ESCALATE-FORCE', 1) == 'OK'
        assert admin.call("CONFIG", "SET", "notify-keyspace-events", "KEA") == "OK"
        res["notify_config"] = b2s(admin.call("CONFIG", "GET", "notify-keyspace-events"))
        shapes = pick_keys(admin, is_redis)
        res["keys"] = shapes
        if not is_redis:
            res["keys_geometry_at_start"] = {s: shards_of(admin, list(k)) for s, k in shapes.items()}
        sub = srv.conn(name="sub")
        sub.send("PSUBSCRIBE", "__keyspace@0__:*", "__keyevent@0__:*")
        sub.read(); sub.read()
        trk = srv.conn(name="trk")
        h = trk.call("HELLO", "3")
        assert isinstance(h, dict), h
        assert trk.call("CLIENT", "TRACKING", "ON") == "OK"
        w = srv.conn(name="writer")
        for shape, (k1, k2) in shapes.items():
            st = {"attempts": 0, "hits": 0, "events_ok": 0, "events_missing": 0,
                  "inval_ok": 0, "inval_missing": 0, "not_hit": 0, "examples": []}
            for i in range(attempts):
                st["attempts"] += 1
                w.call("SET", k1, "init"); w.call("SET", k2, "init")
                # enrol both keys for T
                v1 = trk.call("GET", k1); v2 = trk.call("GET", k2)
                time.sleep(0.02)
                # drain any stale frames
                trk.poll_pushes(0.05); sub.poll_pushes(0.05)
                trk.pushes.clear()
                before_geo = None if is_redis else shards_of(admin, [k1, k2])
                act0 = 0 if is_redis else stat(admin, "script_crossshard_activations")
                esc0 = 0 if is_redis else stat(admin, 'script_escalations')
                val = "v%d" % i
                r = w.call("EVAL", SCRIPT, "2", k1, k2, val)
                # collect up to 1 s, stop early once everything expected arrived
                deadline = time.monotonic() + 1.0
                events = []
                invals = []
                while time.monotonic() < deadline:
                    for f in sub.poll_pushes(0.02):
                        f = b2s(f)
                        if isinstance(f, list) and f and f[0] == "pmessage":
                            events.append((f[2], f[3]))
                    for f in trk.poll_pushes(0.0):
                        if isinstance(f, Push):
                            f = b2s(f)
                            if f[0] == "invalidate":
                                invals.append(f[1])
                    have_ev = {(c, m) for c, m in events}
                    want_ev = {("__keyspace@0__:%s" % k1, "set"), ("__keyspace@0__:%s" % k2, "set"),
                               ("__keyevent@0__:set", k1), ("__keyevent@0__:set", k2)}
                    flat = {x for iv in invals if iv for x in iv}
                    if want_ev <= have_ev and {k1, k2} <= flat:
                        break
                after_geo = None if is_redis else shards_of(admin, [k1, k2])
                act1 = 0 if is_redis else stat(admin, "script_crossshard_activations")
                esc1 = 0 if is_redis else stat(admin, 'script_escalations')
                got = w.call("MGET", k1, k2)
                assert r == 1 and b2s(got) == [val, val], (r, got)
                if is_redis:
                    hit = True
                elif shape == "cross_owner":
                    hit = (before_geo[0][1] != before_geo[1][1] and
                           after_geo[0][1] != after_geo[1][1] and act1 - act0 == 1)
                elif shape == "same_shard":
                    hit = before_geo[0][0] == before_geo[1][0] and after_geo[0][0] == after_geo[1][0]
                else:
                    hit = (before_geo[0][1] == before_geo[1][1] and before_geo[0][0] != before_geo[1][0]
                           and after_geo[0][1] == after_geo[1][1])
                if force and shape != 'same_shard' and not is_redis:
                    hit = hit and esc1 > esc0
                have_ev = {(c, m) for c, m in events}
                flat = {x for iv in invals if iv for x in iv}
                want_ev = {("__keyspace@0__:%s" % k1, "set"), ("__keyspace@0__:%s" % k2, "set"),
                           ("__keyevent@0__:set", k1), ("__keyevent@0__:set", k2)}
                ev_ok = events == [("__keyspace@0__:%s" % k1, "set"),
                                   ("__keyevent@0__:set", k1),
                                   ("__keyspace@0__:%s" % k2, "set"),
                                   ("__keyevent@0__:set", k2)]
                inv_ok = {k1, k2} <= flat
                if not hit:
                    st["not_hit"] += 1
                    continue
                st["hits"] += 1
                st["events_ok" if ev_ok else "events_missing"] += 1
                st["inval_ok" if inv_ok else "inval_missing"] += 1
                if len(st["examples"]) < 3 and (not ev_ok or not inv_ok or i == 0):
                    st["examples"].append({"attempt": i, "events": events, "invalidations": invals,
                                           "geo_before": before_geo, "geo_after": after_geo,
                                           "crossshard_activations_delta": act1 - act0,
                                           "escalations_delta": esc1 - esc0})
            res["shapes"][shape] = st
        res["info_tail"] = {} if is_redis else {
            k: v for k, v in info_dict(admin).items()
            if k.startswith("script_") or k.startswith("notify_") or "tracking" in k}
        for c in (sub, trk, w, admin):
            c.close()
    finally:
        srv.stop()
    with open(out, "a") as f:
        f.write(json.dumps(res) + "\n")
    brief = {s: {k: v for k, v in st.items() if k != "examples"} for s, st in res["shapes"].items()}
    print(geom, json.dumps(brief))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--geom", required=True)
    ap.add_argument("--port", type=int, default=21051)
    ap.add_argument("--attempts", type=int, default=50)
    ap.add_argument("--out", default="t1.jsonl")
    a = ap.parse_args()
    run(a.geom, a.port, a.attempts, a.out)
