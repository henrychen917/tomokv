#!/usr/bin/env python3
"""Compute the controller's placement model both ways from two DEBUG LBSIGNALS captures."""
import subprocess, sys, time

PORT = sys.argv[1] if len(sys.argv) > 1 else "8087"
GAP = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0

def cap():
    out = subprocess.run(["redis-cli", "-p", PORT, "debug", "lbsignals"],
                         capture_output=True, text=True).stdout
    rows = {}
    for line in out.splitlines():
        f = line.split()
        if f[:1] == ["thread"]:
            # thread tid role domain clients iterations ops busy idle cpu ...
            rows[int(f[1])] = dict(role=f[2], iterations=int(f[5]), ops=int(f[6]),
                                   busy=int(f[7]), spins=int(f[15]))
    info = subprocess.run(["redis-cli", "-p", PORT, "info", "stats"],
                          capture_output=True, text=True).stdout
    cmds = 0
    for line in info.splitlines():
        if line.startswith("total_commands_processed:"):
            cmds = int(line.split(":")[1])
    return rows, cmds

a, ca = cap(); time.sleep(GAP); b, cb = cap()
role_ops = {"io": 0.0, "ex": 0.0}; role_busy = {"io": 0.0, "ex": 0.0}
n = {"io": 0, "ex": 0}
for tid, rb in b.items():
    ra = a[tid]
    role = "io" if rb["role"] == "io" else "ex" if rb["role"] == "ex" else None
    if role is None: continue
    n[role] += 1
    ops = rb["ops"] - ra["ops"]; busy = rb["busy"] - ra["busy"]
    it = rb["iterations"] - ra["iterations"]; sp = rb["spins"] - ra["spins"]
    spin_frac = min(1.0, sp / it) if it else 0.0
    role_ops[role] += ops
    role_busy[role] += busy * (1.0 - spin_frac)
cmds = cb - ca
total_units = n["io"] + n["ex"]
print("window: %.1fs  commands=%d  io_threads=%d ex_threads=%d" % (GAP, cmds, n["io"], n["ex"]))
print("  io: ops=%d busy_corrected_ns=%.0f   ops/command=%.3f  ns/op=%.1f  ns/command=%.1f"
      % (role_ops["io"], role_busy["io"], role_ops["io"]/cmds if cmds else 0,
         role_busy["io"]/role_ops["io"] if role_ops["io"] else 0,
         role_busy["io"]/cmds if cmds else 0))
print("  ex: ops=%d busy_corrected_ns=%.0f   ops/command=%.3f  ns/op=%.1f  ns/command=%.1f"
      % (role_ops["ex"], role_busy["ex"], role_ops["ex"]/cmds if cmds else 0,
         role_busy["ex"]/role_ops["ex"] if role_ops["ex"] else 0,
         role_busy["ex"]/cmds if cmds else 0))
if role_ops["io"] and role_ops["ex"] and role_busy["io"] and role_busy["ex"]:
    d_io = role_busy["io"]/role_ops["io"]; d_ex = role_busy["ex"]/role_ops["ex"]
    shipped = total_units * d_io/(d_io+d_ex)
    fixed = total_units * role_busy["io"]/(role_busy["io"]+role_busy["ex"])
    print("  SHIPPED  ns/op-based  io_frac=%.4f  equal_units=%d" % (shipped/total_units, round(shipped)))
    print("  PER-CMD  busy-based   io_frac=%.4f  equal_units=%d" % (fixed/total_units, round(fixed)))
