#!/usr/bin/env python3
"""TRACK-KEYLESS-CAP-DROP: with many tracked keys expiring together, every forgotten key must
get an invalidation (or a flush).  TomoKV's per-shard keyless notification queue holds 4096
records; records beyond that are dropped (notify_events_dropped).

Per attempt (fresh key prefix):
  1. DEBUG SET-ACTIVE-EXPIRE 0 (so the trigger, not the background cycle, reaps in bulk)
  2. W: SET <p>:i v PX <ttl> for i < N (pipelined)
  3. T (RESP3, CLIENT TRACKING ON, default mode): GET every key (enrols N keys)
  4. sleep past the TTL
  5. trigger: SCAN 0 COUNT <big> ... until cursor 0 (SCAN lazily expires the keys it visits on
     both servers), then DEBUG SET-ACTIVE-EXPIRE 1 and wait for DBSIZE 0
  6. collect T's invalidations until 2 s quiet
Verdict per attempt: distinct keys invalidated vs N (a flush counts for all).
HIT (TomoKV) = the old drop counter advanced, or the fixed overflow branch
published a whole-cache invalidation. No FLUSH command runs while tracking is on.
"""
import argparse
import json
import sys
import time


from srv import Server, geometry_text  # noqa: E402
from resp import b2s, Push, info_dict, encode  # noqa: E402


def stat(c, field):
    return int(info_dict(c).get(field, "0"))


class EnrollmentExpired(AssertionError):
    """The finite TTL elapsed before every initial read could enrol its key."""


class CapNotOpened(AssertionError):
    """Fresh state never filled the bounded keyless notification queue."""


def run(geom, port, attempts, n, ttl_ms, trigger, out, mode="default", mget_chunk=50000,
        reap_wait_s=30.0):
    is_redis = geom == "redis"
    srv = Server(geom, port, tag="t3")
    srv.start()
    res = {"item": "TRACK-KEYLESS-CAP-DROP", "geometry": geom, "geometry_text": geometry_text(geom),
           "argv": " ".join(a if a else "''" for a in srv.argv), "n": n, "ttl_ms": ttl_ms,
           "trigger": trigger, "mget_chunk": mget_chunk, "tracking_mode": mode, "attempts": []}
    try:
        w = srv.conn(name="writer", timeout=60)
        trk = srv.conn(name="trk", timeout=60)
        assert isinstance(trk.call("HELLO", "3"), dict)
        for a in range(attempts):
            prefix = "kc%d" % a
            if mode == "bcast":
                assert trk.call("CLIENT", "TRACKING", "ON", "BCAST", "PREFIX", prefix + ":") == "OK"
            else:
                assert trk.call("CLIENT", "TRACKING", "ON") == "OK"
            assert w.call("DEBUG", "SET-ACTIVE-EXPIRE", "0") == "OK"
            keys = ["%s:%d" % (prefix, i) for i in range(n)]
            chunk = 5000
            first_set = time.monotonic()
            for i in range(0, n, chunk):
                rs = w.pipeline([("SET", k, "v", "PX", str(ttl_ms)) for k in keys[i:i + chunk]], timeout=60)
                assert all(r == "OK" for r in rs), rs[:3]
            t_set = time.monotonic()
            if mode != "bcast":
                if mode == "exec":
                    chunk = 500
                for i in range(0, n, chunk):
                    commands = [("GET", k) for k in keys[i:i + chunk]]
                    if mode == "exec":
                        framed = trk.pipeline([("MULTI",), *commands, ("EXEC",)], timeout=60)
                        assert framed[0] == "OK" and framed[1:-1] == ["QUEUED"] * len(commands), framed[:3]
                        rs = framed[-1]
                        assert isinstance(rs, list) and len(rs) == len(commands), rs
                    else:
                        rs = trk.pipeline(commands, timeout=60)
                    if any(r is None for r in rs) and time.monotonic() - first_set >= ttl_ms / 1000:
                        raise EnrollmentExpired(
                            f"initial enrolment reached expired keys at batch {i // chunk}; "
                            f"elapsed={time.monotonic() - first_set:.3f}s ttl={ttl_ms}ms")
                    assert all(r == b"v" for r in rs), [r for r in rs if r != b"v"][:3]
            enrol_done = time.monotonic() - t_set
            trk.poll_pushes(0.05)
            trk.pushes.clear()
            info0 = {} if is_redis else info_dict(w)
            dropped0 = int(info0.get("notify_events_dropped", 0))
            fired0 = int(info0.get("notify_events_fired", 0))
            # wait for the TTL to pass
            remain = ttl_ms / 1000.0 - (time.monotonic() - t_set) + 0.3
            if remain > 0:
                time.sleep(remain)
            dbsize_before = w.call("DBSIZE")
            t0 = time.monotonic()
            scans = 0
            if trigger == "scan":
                cur = "0"
                while True:
                    r = w.call("SCAN", cur, "COUNT", "100000", timeout=60)
                    scans += 1
                    cur = r[0].decode() if isinstance(r[0], bytes) else str(r[0])
                    if cur == "0":
                        break
            elif trigger == "keys":
                w.call("KEYS", prefix + ":*", timeout=60)
                scans = 1
            elif trigger == "mget":
                for i in range(0, n, mget_chunk):
                    w.call("MGET", *keys[i:i + mget_chunk], timeout=60)
                    scans += 1
            elif trigger == "active":
                pass
            trig_s = time.monotonic() - t0
            assert w.call("DEBUG", "SET-ACTIVE-EXPIRE", "1") == "OK"
            # wait until every key is gone (both servers reap the rest actively)
            t_reap = time.monotonic()
            dbsize_trace = []
            while time.monotonic() - t_reap < reap_wait_s:
                d = w.call("DBSIZE")
                if not dbsize_trace or dbsize_trace[-1][1] != d:
                    dbsize_trace.append((round(time.monotonic() - t_reap, 2), d))
                if d == 0:
                    break
                time.sleep(0.05)
            dbsize_after = w.call("DBSIZE")
            frames = trk.read_frames_until_quiet(quiet=2.0, max_total=60.0)
            frames = [p for _, p in trk.pushes]
            trk.pushes.clear()
            invalidated = set()
            flushes = 0
            for f in frames:
                f = b2s(f)
                if isinstance(f, list) and f and f[0] == "invalidate":
                    if f[1] is None:
                        flushes += 1
                    else:
                        invalidated.update(x for x in f[1] if x.startswith(prefix + ":"))
            info1 = {} if is_redis else info_dict(w)
            dropped = int(info1.get("notify_events_dropped", 0)) - dropped0
            fired = int(info1.get("notify_events_fired", 0)) - fired0
            # The repair correctly stops counting a tracking invalidation as
            # dropped. Its whole-cache frame witnesses the same overflow path.
            hit = True if is_redis else dropped > 0 or flushes > 0
            row = {"attempt": a, "n": n, "dbsize_before_trigger": dbsize_before,
                   "dbsize_after": dbsize_after, "trigger_calls": scans,
                   "trigger_seconds": round(trig_s, 3), "enrol_seconds": round(enrol_done, 3),
                   "invalidated_distinct": len(invalidated), "flush_frames": flushes,
                   "missing": 0 if flushes else n - len(invalidated),
                   "push_frames": len(frames), "notify_events_dropped_delta": dropped,
                   "notify_events_fired_delta": fired, "hit": hit,
                   "dbsize_trace": dbsize_trace[-6:]}
            if not is_redis:
                i1 = info1
                row["tracking_info"] = {k: v for k, v in i1.items() if "tracking" in k or "invalidat" in k}
            res["attempts"].append(row)
            print(geom, json.dumps({k: v for k, v in row.items() if k != "tracking_info"}), flush=True)
            assert trk.call("CLIENT", "TRACKING", "OFF") == "OK"
            trk.poll_pushes(0.2)
            trk.pushes.clear()
        w.close(); trk.close()
    finally:
        srv.stop()
    # A real lost invalidation is never re-rolled, even if another arming
    # diagnostic is absent; the caller must retain it as a failed assertion.
    if not is_redis and all(row['missing'] == 0 for row in res['attempts']) and \
            any(not row['hit'] for row in res['attempts']):
        raise CapNotOpened(json.dumps(res))
    with open(out, "a") as f:
        f.write(json.dumps(res) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--geom", required=True)
    ap.add_argument("--port", type=int, default=21053)
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--n", type=int, default=200000)
    ap.add_argument("--ttl-ms", type=int, default=8000)
    ap.add_argument("--trigger", default="scan", choices=["scan", "keys", "mget", "active"])
    ap.add_argument("--mode", default="default", choices=["default", "bcast"])
    ap.add_argument("--mget-chunk", type=int, default=50000)
    ap.add_argument("--reap-wait-s", type=float, default=30.0)
    ap.add_argument("--out", default="t3.jsonl")
    a = ap.parse_args()
    run(a.geom, a.port, a.attempts, a.n, a.ttl_ms, a.trigger, a.out, a.mode, a.mget_chunk,
        a.reap_wait_s)
