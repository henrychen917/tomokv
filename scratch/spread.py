#!/usr/bin/env python3
"""Is the cross-thread work spread EVIDENCE of imbalance, or is it one thread's own bursts?

Samples DEBUG LBSIGNALS on a fixed cadence and, for the io role and the ex role separately,
reports two quantities that the controller and the client-weight planner both have to tell apart:

  CROSS-THREAD SPREAD -- at one instant, (max-min) of the per-thread busy fraction across the
      role's threads.  This is the shape of signal every spread-threshold actuator fires on.
  TEMPORAL SPREAD     -- for ONE thread, (max-min) of its own busy fraction over the run.  If a
      single thread's load swings by as much over time as the threads differ from each other at
      an instant, an instantaneous spread reading carries no information about persistent
      imbalance: it is the same burstiness seen sideways.

Also tracks the server's own client-weight spread gauge and the flip counters, so a flip that
happens mid-run is attributable.

usage: spread.py PORT SECONDS [interval]
"""
import subprocess, sys, time, statistics

PORT = sys.argv[1]
SECS = float(sys.argv[2])
GAP = float(sys.argv[3]) if len(sys.argv) > 3 else 0.25


def cli(*args):
    return subprocess.run(["redis-cli", "-p", PORT, *args],
                          capture_output=True, text=True, timeout=15).stdout


def snap():
    rows = {}
    for line in cli("debug", "lbsignals").splitlines():
        f = line.split()
        if f[:1] == ["thread"]:
            rows[int(f[1])] = (f[2], int(f[7]), int(f[8]))   # role, busy_ns, idle_ns
    info = cli("info", "all")
    kv = {}
    for line in info.splitlines():
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            kv[k] = v
    return rows, kv, time.monotonic()


prev, kv0, t0 = snap()
series = {}          # tid -> [busy fraction per interval]
roles = {}
cross = {"io": [], "ex": []}
lbspread = []
end = time.monotonic() + SECS
while time.monotonic() < end:
    time.sleep(GAP)
    cur, kv, t = snap()
    dt = (t - t0) * 1e9
    if dt <= 0:
        continue
    frac = {}
    for tid, (role, busy, idle) in cur.items():
        if tid not in prev:
            continue
        prole, pbusy, pidle = prev[tid]
        if prole != role:
            continue                      # a flip changed this thread's role; skip the boundary
        dbusy = busy - pbusy
        didle = idle - pidle
        wall = dbusy + didle
        if wall <= 0:
            continue
        frac[tid] = dbusy / wall
        roles[tid] = role
        series.setdefault(tid, []).append(dbusy / wall)
    for role in ("io", "ex"):
        vals = [v for tid, v in frac.items() if roles.get(tid) == role]
        if len(vals) >= 2:
            cross[role].append(max(vals) - min(vals))
    try:
        lbspread.append(float(kv.get("tomokv_keylb_client_weight_spread_current", "nan")))
    except ValueError:
        pass
    prev, t0 = cur, t

_, kvN, _ = snap()


def stat(name, values):
    if not values:
        return "%-28s n=0" % name
    return ("%-28s n=%-4d mean=%.4f  p50=%.4f  max=%.4f"
            % (name, len(values), statistics.fmean(values),
               statistics.median(values), max(values)))


print("port=%s window=%.0fs interval=%.2fs samples=%d"
      % (PORT, SECS, GAP, len(cross["io"])))
for role in ("io", "ex"):
    print("  role %s" % role)
    print("    " + stat("CROSS-THREAD spread", cross[role]))
    per = [(tid, vals) for tid, vals in series.items()
           if roles.get(tid) == role and len(vals) > 2]
    temporal = [max(v) - min(v) for _, v in per]
    swings = [statistics.pstdev(v) for _, v in per]
    means = [statistics.fmean(v) for _, v in per]
    if temporal:
        print("    %-28s per-thread mean=%.4f  max=%.4f"
              % ("TEMPORAL spread (max-min)", statistics.fmean(temporal), max(temporal)))
        print("    %-28s per-thread mean=%.4f" % ("TEMPORAL stdev", statistics.fmean(swings)))
        print("    %-28s across threads = %.4f (max-min of the TIME-AVERAGED loads)"
              % ("time-averaged imbalance", (max(means) - min(means)) if len(means) > 1 else 0.0))
        if cross[role]:
            print("    ratio  mean instantaneous cross-thread spread / mean temporal spread = %.2f"
                  % (statistics.fmean(cross[role]) / statistics.fmean(temporal)
                     if statistics.fmean(temporal) else float("inf")))
print("  client-weight spread gauge: " + stat("tomokv_keylb_..._current", 
      [v for v in lbspread if v == v]))
for key in ("flip_completed", "flip_clients_transferred", "flipctl_triggers",
            "flipctl_fingerprint_triggers", "flipctl_rate_surge_triggers",
            "flipctl_rate_collapse_triggers", "flipctl_null_maneuvers",
            "flipctl_model_holds", "tomokv_keylb_client_moves",
            "tomokv_keylb_bucket_moves", "flipctl_anchor_io", "flipctl_anchor_ex",
            "lb_flip_client_weight_spread_before", "lb_flip_client_weight_spread_after",
            "lb_flip_bucket_weight_spread_before", "lb_flip_bucket_weight_spread_after"):
    if key in kvN:
        print("  %-42s %s -> %s" % (key, kv0.get(key, "-"), kvN[key]))
