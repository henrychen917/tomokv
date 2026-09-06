#!/usr/bin/env python3
"""Per-role spin/busy/idle decomposition from two DEBUG LBSIGNALS captures.

Answers: does the controller's utilization input count synchronization spin as busy work?
"""
import subprocess, sys, time
PORT = sys.argv[1] if len(sys.argv) > 1 else "8087"
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 6.0

def cap():
    out = subprocess.run(["redis-cli", "-p", PORT, "debug", "lbsignals"],
                         capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        f = line.split()
        if f[:1] == ["thread"]:
            rows[int(f[1])] = dict(role=f[2], iterations=int(f[5]), ops=int(f[6]),
                                   busy=int(f[7]), idle=int(f[8]), cpu=int(f[9]),
                                   spins=int(f[15]))
    info = subprocess.run(["redis-cli", "-p", PORT, "info", "stats"],
                          capture_output=True, text=True).stdout
    cmds = next((int(l.split(":")[1]) for l in info.splitlines()
                 if l.startswith("total_commands_processed:")), 0)
    return rows, cmds

a, ca = cap(); time.sleep(GAP); b, cb = cap()
cmds = cb - ca
agg = {}
for tid, rb in b.items():
    ra = a[tid]; role = rb["role"]
    if role not in ("io", "ex"): continue
    d = agg.setdefault(role, dict(n=0, it=0, ops=0, busy=0, idle=0, spins=0, corrected=0.0))
    it = rb["iterations"]-ra["iterations"]; sp = rb["spins"]-ra["spins"]
    busy = rb["busy"]-ra["busy"]
    d["n"] += 1; d["it"] += it; d["ops"] += rb["ops"]-ra["ops"]
    d["busy"] += busy; d["idle"] += rb["idle"]-ra["idle"]; d["spins"] += sp
    d["corrected"] += busy * (1.0 - (min(1.0, sp/it) if it else 0.0))
print("window %.1fs  commands=%d" % (GAP, cmds))
for role in ("io", "ex"):
    d = agg[role]
    wall = d["busy"] + d["idle"]
    print("  %s x%d: raw_busy_frac=%.4f  spins/iter=%.4f  raw_busy=%.3fs  "
          "spin-corrected_busy=%.3fs  (correction removes %.1f%%)  ops/cmd=%.3f"
          % (role, d["n"], d["busy"]/wall if wall else 0,
             d["spins"]/d["it"] if d["it"] else 0,
             d["busy"]/1e9, d["corrected"]/1e9,
             100.0*(1 - d["corrected"]/d["busy"]) if d["busy"] else 0,
             d["ops"]/cmds if cmds else 0))
io, ex = agg["io"], agg["ex"]
print("  io_frac from RAW busy            = %.4f" % (io["busy"]/(io["busy"]+ex["busy"])))
print("  io_frac from SPIN-CORRECTED busy = %.4f   <-- the controller's input"
      % (io["corrected"]/(io["corrected"]+ex["corrected"])))
