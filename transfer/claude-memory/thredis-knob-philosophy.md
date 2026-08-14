---
name: thredis-knob-philosophy
description: "User's knob design rules (2026-07-03): keep only numeric tunables; 0=off means no-alloc; thresholds/decays self-derive via ratios + self-measurement, never hardware-encoding constants"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

User's knob design philosophy (2026-07-03), governs all v13+ config work:

1. **Binary opt knobs don't exist** — benign opts get hardwired (done: waves 1+3 retired 18 knobs).
   What remains configurable is **numbers only**: batch/stage widths, queue lengths, pipeline depths,
   thresholds, decay periods, counts.
2. **0 = off, and off must mean NO work and NO allocation** — not just a skipped branch. If a knob is
   0, its feature should not allocate rings/buffers/tables at init.
3. **Thresholds and decays must not be hardcoded magic numbers.** Make them dynamic — but "dynamic
   that makes sense": self-derived from **dimensionless ratios** (pool fill %, hit rates) and
   **self-measured quantities** (EWMA value sizes, detected L3 via sysfs, dbSize×entry-footprint),
   so the server adapts **without the operator needing hardware knowledge**. Auto-derivation beats
   both hardcoding AND requiring the user to know their cache sizes. Explicit numeric override stays
   available; -1/auto = self-derive where meaningful.

**Why:** knob collapse for the 2-version endgame ([[thredis-endgame-two-versions]]); portable defaults
for the Threadripper without re-tuning; ratios transfer across machines, absolutes don't.
**Applied so far:** prefetch stage widths (0=off, stateless ✓); flagship fix = prefetch-adaptive-min-keys
gets -1=AUTO (derive from detected L3 + tracked entry footprint instead of the laptop-encoded 8M);
zerocopy-min-value 0=OFF; pool decay period knob (0=never) + ratio-based skip logic kept dimensionless;
worker spin cadence exposed as knobs.
**Addendum (user, 2026-07-04) — controllers, not calibrators:** auto-tune must NEVER "tune to a point
and stop" — workloads shift on a dime. Every adaptive mechanism must be a CONTINUOUS, simple
mathematical controller (PID-spirit: react to the current signal every tick, forever), with no
dependence on server runtime/uptime/phases (no calibration-then-lock, no learned-then-frozen state).
Bootstrap seeding is fine; convergence guards must self-reset when the pattern changes. **Corollary:
when the controller is the only correct mode, DELETE its knobs entirely** (applied: reshard
imbalance/alpha/fast/progress/settle/core-aware knobs deleted — auto is THE algorithm; prefetch
adaptive-min-keys deleted — L3-derived gate always; pf-w-value-adaptive + pf-value-cache-kb deleted —
value width always adapts with budget = L3/(2·workers)). One-time HARDWARE reads (sysfs L3) are fine —
that's machine identity, not runtime state.

**Addendum (2026-07-04) — "no stall, no feature" doctrine:** the user's recurring v4-era experience
("every cool new idea ends up 1-2% slower consistently") is the unconditional-cost/conditional-benefit
asymmetry: hot-loop machinery taxes EVERY op, while its benefit needs a bottleneck that may not exist
(proven this session: prefetch = identical L1 misses on/off; multi-CDB = no contention on 1 CCD; VF =
no same-key runs in real traffic). Every big win ever shipped was SUBTRACTIVE (E1 +74% removed a stall,
zerocopy +24% removed a memcpy, LB +133%, jemalloc +54%, deletions always net-positive). RULE: before
implementing, demand perf-counter evidence of the stall the idea removes; no evidence → notebook, not
hot loop. Additive ideas ship default-off until multi-regime proof; deletions ship immediately. The
"losers" are early, not wrong — parked behind widths/knobs for the Threadripper's bottlenecks.

**Final form (user, 2026-07-04) — dual-mode convention:** where an override is legitimately useful,
controller-owned values expose ONE int knob: **0 (default) = auto (the controller drives), N = pin**.
Applied: tomokv-l3-kb (VMs hide sysfs topology), reshard-imbalance-pct/-chunk, prefetch-min-keys,
pf-value-budget-kb, worker-spin, pool-decay-ops (3s), num-cdb (pre-existing shape). Internal-only
controller constants (alphas, settle, progress, k, floors, decay-idle) stay hardcoded — no knob.
The operator tunes nothing by default; every knob is an explicit choice to stop the controller.
