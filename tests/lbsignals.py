#!/usr/bin/env python3
# lbsignals battery -- proves the LB signal READ side reports real, conserved quantities.
#
# Non-vacuous by construction: the load leg asserts OP CONSERVATION (io ops delta == ex ops delta
# == commands sent), which can only hold if both roles' counters are live and the capture path
# reads the right memory. A dump that always returned zeros or stale rows fails every leg.
#
# Thread modes. Under --thread-mode 2s both rollups are live and every leg runs. Under 1s every
# thread is labelled `io` and the `ex` rollup is empty BY CONSTRUCTION (src/cmd/lbsignals.cc:156),
# so the ex-side legs are skipped WITH THAT REASON, the io-side legs still assert conservation, and
# the emptiness of the ex rollup is itself asserted (a 1s boot reporting ex threads would be a
# placement defect). Exact 1s conservation (N vs 2N per fused op) has not been pinned by a run, so
# the 1s io leg asserts >= N and prints the delta for the first run to pin it.
#
# The client is tests/_lib.Conn, a real RESP reader. The previous reader was `sleep 0.05` plus one
# recv() with a "replies arrive in one burst" heuristic: a DEBUG LBSIGNALS dump that arrives in two
# segments was truncated and the row failed on a missing field with no server defect behind it
# (AUDIT-TESTS F3). Fixed sleeps that only waited for counters to settle are now bounded polls.
import sys
import time

import _lib

HOST, PORT = sys.argv[1], int(sys.argv[2])
SANE_AGE_US = 60_000_000
AGE_FIELDS = ("queue_delay_ewma_us", "oldest_age_us", "oldest_age_ewma_us",
              "oldest_age_min_us", "oldest_age_max_us")
ROLLUP_AGE_FIELDS = ("queue_delay_ewma_us", "oldest_age_min_us", "oldest_age_max_us",
                     "oldest_age_ewma_us")

checks = 0
skipped = []


def ok(label, cond, detail=""):
    global checks
    if not cond:
        print(f"FAIL {label} {detail}", flush=True)
        sys.exit(1)
    checks += 1


def skip(label, reason):
    skipped.append(label)
    print(f"  SKIP {label} -- {reason}", flush=True)


def capture(conn):
    snap = _lib.lbsignals(conn)
    threads = [t._asdict() for t in snap.threads]
    shards = [{"sid": s.sid, "owner": s.owner, "ops": s.ops, "foreign": s.foreign}
              for s in snap.shards]
    return threads, shards, snap.rollups, snap.derived


s = _lib.Conn(HOST, PORT, timeout=10)
MODE = _lib.thread_mode(s)
FUSED = MODE == "1s"

# ---- leg 1: structure + idle sanity --------------------------------------------------------------
t1, sh1, roll1, der1 = capture(s)
ok("thread rows exist", len(t1) >= 2, str(len(t1)))
roles = {r["role"] for r in t1}
if FUSED:
    ok("1s: every thread is labelled io", roles == {"io"}, str(roles))
    ok("1s: ex rollup is empty by construction", roll1["ex"]["threads"] == 0,
       str(roll1["ex"]["threads"]))
else:
    ok("both roles present", {"io", "ex"} <= roles, str(roles))
ok("shard rows exist", len(sh1) >= 1)
ok("rollup thread counts match rows",
   roll1["io"]["threads"] == sum(1 for r in t1 if r["role"] == "io")
   and roll1["ex"]["threads"] == sum(1 for r in t1 if r["role"] == "ex"))
ok("every shard names a live thread as owner",
   {x["owner"] for x in sh1} <= {r["tid"] for r in t1},
   str(sorted({x["owner"] for x in sh1})))
ok("cpu_ns live on every thread", all(r["cpu_ns"] > 0 for r in t1))
ok("ratio_star fields present", "ratio_star_io_frac" in der1 and "ratio_star_io" in der1)
f = float(der1["ratio_star_io_frac"])
ok("ratio_star_io_frac in (0,1)", 0.0 <= f <= 1.0, str(f))
ok("idle age exports are sane",
   all(0 <= r[field] <= SANE_AGE_US for r in t1 for field in AGE_FIELDS))

it1 = {r["tid"]: r["iterations"] for r in t1}
ds1 = {r["tid"]: r["depth_samples"] for r in t1}
# Iterations advance on their own (timers tick the loop); poll for it rather than sleeping a
# fixed 0.4 s and hoping.
t2 = _lib.wait_until(
    lambda: (lambda rows: rows if all(r["iterations"] > it1.get(r["tid"], 0) for r in rows)
             else None)(capture(s)[0]), 3.0, interval=0.1)
ok("iterations advance while idle", t2 is not None)
if FUSED:
    skip("depth is time-gated, not iteration-weighted",
         "the depth sampler is an executor-queue instrument; the ex rollup is empty in 1s")
else:
    ok("depth is time-gated, not iteration-weighted",
       all(0 < r["depth_samples"] - ds1.get(r["tid"], 0)
           < r["iterations"] - it1.get(r["tid"], 0) for r in t2 if r["role"] == "ex"))

# ---- leg 2: op conservation under load -----------------------------------------------------------
_, _, roll_a, _ = capture(s)
N = 20000
w = _lib.Conn(HOST, PORT, timeout=10)
w.raw(b"".join(_lib.encode("SET", b"lbk%06d" % i, "vvvvvvvv") for i in range(N)))
acked = 0
for _ in range(N):
    if w.read() != b"OK":
        break
    acked += 1
ok("load leg completed", acked == N, f"{acked} OK replies of {N}")
# Counters are per-thread and land within a pass; wait for the io rollup to show the load rather
# than sleeping a fixed 0.3 s.
ok("io ops reached the rollup",
   _lib.wait_until(lambda: capture(s)[2]["io"]["ops"] - roll_a["io"]["ops"] >= N, 3.0,
                   interval=0.05))
_, sh_b, roll_b, der_b = capture(s)

dio = roll_b["io"]["ops"] - roll_a["io"]["ops"]
dex = roll_b["ex"]["ops"] - roll_a["ex"]["ops"]
# The capture connections' own DEBUG/INFO commands add a handful of ops; bound, don't equate.
if FUSED:
    ok("1s: io ops advanced by at least the load", dio >= N, f"dio={dio} (N={N}; pin N vs 2N)")
    skip("ex ops conserved", f"ex rollup empty in 1s (dex={dex})")
else:
    ok("io ops conserved", N <= dio <= N + 50, f"dio={dio}")
    ok("ex ops conserved", N <= dex <= N + 50, f"dex={dex}")
ok("io busy advanced under load", roll_b["io"]["busy_ns"] > roll_a["io"]["busy_ns"])
if FUSED:
    for label in ("ex busy advanced under load", "ex depth sampled", "sampled queue delay fired",
                  "sampled queue delay EWMA valid", "sampled oldest-entry age fired",
                  "no backpressure at this load"):
        skip(label, "ex rollup empty in 1s")
    ok("1s: io age exports stay bounded",
       all(0 <= roll_b["io"][field] <= SANE_AGE_US for field in ROLLUP_AGE_FIELDS))
else:
    ok("ex busy advanced under load", roll_b["ex"]["busy_ns"] > roll_a["ex"]["busy_ns"])
    ok("ex depth sampled", roll_b["ex"]["avg_depth"] >= 0.0)
    ok("sampled queue delay fired",
       roll_b["ex"]["queue_delay_samples"] > roll_a["ex"]["queue_delay_samples"])
    ok("sampled queue delay EWMA valid", roll_b["ex"]["queue_delay_ewma_us"] >= 0.0)
    ok("sampled oldest-entry age fired", roll_b["ex"]["oldest_age_max_us"] > 0)
    ok("sampled age exports stay bounded",
       all(0 <= roll_b[role][field] <= SANE_AGE_US for role in ("io", "ex")
           for field in ROLLUP_AGE_FIELDS))
    ok("no backpressure at this load",
       roll_b["ex"]["full_events"] == roll_a["ex"]["full_events"])
ok("shard ops sum >= N", sum(x["ops"] for x in sh_b) >= N)
ok("clean pinning: zero foreign ops", sum(x["foreign"] for x in sh_b) == 0,
   str(sum(x["foreign"] for x in sh_b)))

# ---- leg 3: INFO # LB carries the derived block --------------------------------------------------
lb = _lib.info(s, "LB")
for field in ("lb_io_threads", "lb_ex_threads", "lb_io_busy_frac", "lb_ex_busy_frac",
              "lb_io_ns_per_op", "lb_ex_ns_per_op", "lb_ratio_star_io_frac",
              "lb_foreign_op_frac", "lb_io_queue_delay_samples",
              "lb_ex_queue_delay_samples", "lb_io_queue_delay_ewma_us",
              "lb_ex_queue_delay_ewma_us", "lb_io_oldest_age_min_us",
              "lb_io_oldest_age_max_us", "lb_io_oldest_age_ewma_us",
              "lb_ex_oldest_age_min_us", "lb_ex_oldest_age_max_us",
              "lb_ex_oldest_age_ewma_us"):
    ok(f"INFO has {field}", field in lb)
ok("INFO io ns_per_op parses > 0", float(lb["lb_io_ns_per_op"]) > 0.0, lb["lb_io_ns_per_op"])
if FUSED:
    skip("INFO ex ns_per_op parses > 0", "ex rollup empty in 1s")
    ok("1s: INFO lb_ex_threads is 0", lb["lb_ex_threads"] == "0", lb["lb_ex_threads"])
else:
    ok("INFO ex ns_per_op parses > 0", float(lb["lb_ex_ns_per_op"]) > 0.0, lb["lb_ex_ns_per_op"])
for field in ("lb_io_queue_delay_ewma_us", "lb_ex_queue_delay_ewma_us",
              "lb_io_oldest_age_min_us", "lb_io_oldest_age_max_us",
              "lb_io_oldest_age_ewma_us", "lb_ex_oldest_age_min_us",
              "lb_ex_oldest_age_max_us", "lb_ex_oldest_age_ewma_us"):
    value = float(lb[field])
    ok("INFO %s is sane" % field, 0 <= value <= SANE_AGE_US, str(value))

print(f"LBSIGNALS: {checks} checks ok (thread-mode {MODE}, {len(skipped)} skipped: "
      f"{', '.join(skipped) if skipped else 'none'})", flush=True)
