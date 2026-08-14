---
name: thredis-flip-no-machine-constants
description: "OWNER RULE — flip must have NO machine-dependent constants and behave identically on any machine; audit found settle time is structurally steps x window, so it scales LINEARLY with core count"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Owner, 2026-08-09:** "for flip no constants, work on any machine the same way."

Consistent with [[thredis-knob-philosophy]] and with the prefetch-knob retirement rationale in
config.c: *"A number typed into a config file could only restate what the server already measures,
and would then be wrong on the next machine."*

# Audit of the flip controller (2s-flip-iowait @e566c3f4f)

**Already self-deriving — fine:**
- `gstep = ln((ni+1)/ni) + ln(ne/(ne-1))` from LIVE thread counts; `gfloor = gstep/2`
- `occ_clip = 100 - (1/FESC_ALPHA - 1)` — derived from the filter's own quantisation
- `QCAP = (server.ex_queue_size > 0) ? server.ex_queue_size : 4096.0` — tracks the real ring.
  **CORRECTION to my earlier note "QCAP = 2048 always"** — that was the observed value, not a hardcode.
- judge band `max(2*sigma, 0.02*best)` — sigma from measured noise

**Dimensionless policy constants — port fine:** `FLIP_R_BAND 0.03`, `FLIP_R_QUIET 0.02`,
`FLIP_R_FAR 0.69` (= ln 2, exactly 2x imbalance), `FLIP_BOUND_SAT 0.75`, `FESC_ALPHA 0.25`,
`FLIP_LOAD_SHIFT 3.0`.

**TIME/TICK constants — where machine dependence actually lives:** `FESC_MEAS_N 16` (~4s),
`FESC_WAIT_BASE 8` (~2s), `FLIP_SUSTAIN 8`, `FLIP_WAIT_KEEP 4`, `FLIP_WAIT_REVERT 12`,
`FESC_WARM_CAP 48`, `FLIP_R_QUIET_LOUD 120`.

# THE FINDING: settle time is steps x window, so it scales with core count

Each directed step costs one measure window plus one wait: `(FESC_MEAS_N + FESC_WAIT_BASE)` =
24 ticks ~= **6s per step**. Measured on 8 threads (flipauto phase 2a, booting from the worst config):

    io2/ex6 -> io7/ex1   5 steps   settle 32s
    io7/ex1 -> io4/ex4   3 steps + overshoot/revert   settle 38s

The arithmetic matches the measurement, so this is structural, not incidental.

**Consequence for the 24-core Threadripper target** ([[thredis-final-server-specs]]): io12/ex12 ->
io23/ex1 is 11 steps ~= **66 seconds**. Identical code and constants, double the convergence time.
The controller would NOT behave the same on that machine, which is exactly what the owner rules out.

# The fix that satisfies the rule without adding a constant

Make the STEP SIZE derive from distance instead of always moving one thread. `|lr_ewma|` already
measures how imbalanced the split is and `FLIP_R_FAR` (ln 2 = 2x) already names "far". Taking a
multi-thread step while far makes convergence sub-linear in distance rather than linear, and the
step size is derived from the SAME signal the trigger already uses -- no new tunable.

Guard: a big step must still be judged by throughput and reverted like any other, or a coarse step
becomes a way to overshoot faster. Keep the existing measure/judge/revert machinery; only the
step MAGNITUDE changes.

Also noted: `#define FLIP_SUSTAIN 8` appears TWICE in server.c (identical value, so it compiles).
Cosmetic, but worth collapsing.
