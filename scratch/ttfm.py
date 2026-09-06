#!/usr/bin/env python3
"""ttfm.py TRACE.txt BOOT_IO BOOT_EX -- from a 1 Hz trace of `t total_commands io ex`, report
time-to-first-move, moves-after-stabilization, and steady-state rate as three separate numbers.
  time-to-first-move = first second the live split differs from the boot split (None if it never moved)
  moves-after-stab   = split changes after the FIRST 20 s window with no split change (the owner's
                       thrash definition: moves after it settled)
  steady rate        = mean ops/s over the last 30 s from total_commands deltas
  final split, and the whole split timeline."""
import sys
trace, bio, bex = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rows = []
for line in open(trace, errors="replace"):
    f = line.split()
    if len(f) < 3: continue
    try:
        t = int(f[0]); tc = int(f[1])
        if ":" in f[2]: io, ex = (int(x) for x in f[2].split(":"))
        elif len(f) >= 4: io, ex = int(f[2]), int(f[3])
        else: continue
    except ValueError:
        continue
    rows.append((t, tc, io, ex))
if not rows:
    print("no trace"); sys.exit(0)
boot = (bio, bex)
splits = [(t, (io, ex)) for t, _, io, ex in rows]
# time to first move
ttfm = next((t for t, s in splits if s != boot), None)
# transitions
trans = []
prev = splits[0][1]
for t, s in splits:
    if s != prev:
        trans.append((t, prev, s)); prev = s
# first stabilization: the earliest t AT OR AFTER THE FIRST MOVE after which the split holds for
# >= 20 s (a boot split held while the controller is still searching is not a settled anchor); a
# cell that never moved is stable from its start.
stab_t = None
first_move = trans[0][0] if trans else 0
for k, (t, s) in enumerate(splits):
    if t < first_move: continue
    horizon = [ss for tt, ss in splits if t <= tt <= t + 20]
    if horizon and all(ss == s for ss in horizon) and (t + 20 <= splits[-1][0]):
        stab_t = t; stab_split = s; break
moves_after_stab = sum(1 for tt, _, _ in trans if stab_t is not None and tt > stab_t)
# steady state: last 30 s ops/s from total_commands
tail = [r for r in rows if r[0] >= rows[-1][0] - 30]
steady = (tail[-1][1] - tail[0][1]) / (tail[-1][0] - tail[0][0]) if len(tail) > 1 and tail[-1][0] > tail[0][0] else 0
timeline = ">".join(f"{s[0]}:{s[1]}@{t}s" for t, s in [(splits[0][0], splits[0][1])] + [(t, s) for t, a, s in trans])
print("ttfm=%s moves_after_stab=%d stab@=%s steady=%.0f final=%d:%d flips_in_trace=%d" % (
    ttfm if ttfm is not None else "NEVER", moves_after_stab,
    stab_t if stab_t is not None else "never", steady, splits[-1][1][0], splits[-1][1][1], len(trans)))
print("  splits: " + timeline)
