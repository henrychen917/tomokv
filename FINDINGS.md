# Occupancy EWMA quantisation fix

## What changed

- Added Q4 (`percentage points * 16`) IO-role and EX-role occupancy EWMAs to the flip controller.
  They use the existing `FESC_ALPHA` recurrence and the same per-role integer occupancy means; only
  the stored representation is finer.
- Modes 1, 2, and 3 now convert those Q4 values back to the existing dimensionless utilization
  units by dividing by `16 * 100` before the unchanged saturation calculations.
- Retained and continuously update the original whole-percentage EWMAs as mode 0's control-arm
  shadows. Maintaining both filters also means the modifiable signal knob can change at runtime
  without cold-starting either representation.
- Added the required warning beside `FLIP_BOUND_SAT`: its quoted measured occupancies predate this
  fix and include the old filter's up-to-three-percentage-point under-read.

## Comparisons re-expressed

There are two representation-sensitive uses:

1. `u_io` and `u_ex` previously used `whole_percent / 100`. In modes 1-3 they now use
   `q4_percent / (16 * 100)`. These are the same dimensionless `[0,1]` units, so the `1.0` clamps,
   `io_sat`/`ex_sat` construction, `FLIP_BOUND_SAT`, ratio/worker signals, band, and granularity
   floor retain their existing meanings and constants.
2. Mode 3's `floor_blind` test asks whether the EX occupancy filter has reached its representable
   full-scale plateau. The old whole-percent recurrence plateaued at `100 - 3 = 97`; the same
   recurrence in Q4 plateaus at `(100 * 16) - 3 = 1597`, or 99.8125%. The comparison is therefore
   made directly against `ex_occ_smooth_q4 >= 1597`. This preserves the comparison's semantic
   meaning rather than retaining the stale numeric value 97.

No other comparison reads either stored occupancy field directly. The node-idle test continues to
use the raw per-tick integer `io_occ_mean`, exactly as before.

## Mode 0

Mode 0 stays bit-identical in its decisions. Its original update expressions and whole-percent
`/ 100.0` decision operands are unchanged. The Q4 filters are maintained alongside them but cannot
feed mode-0 saturation, signals, gates, or trigger decisions. Its worker-signal log suffix also
remains empty as before.

The finer representation is gated out of mode 0 because feeding it into the ratio signal would
necessarily change decision operands and invalidate the A/B control arm.

## Precision limit and rejected changes

Q4 reduces the EWMA dead zone from three percentage points to three sixteenths of a percentage
point. With the existing truncate-toward-zero recurrence, a sustained 100% input reaches
`1597 / 1600 = 0.998125`, which prints as `u_ex=0.998` in the three-decimal `W(...)` suffix. It is
therefore above the old hard ceiling of 0.97, but is not literally 1.000. Making the finite-precision
recurrence land on exact endpoints would require an endpoint snap, a minimum-step rule, or another
rounding rule. I rejected those because they would change filter dynamics beyond the requested Q4
representation fix and would introduce a new rule into frozen decision inputs.

I did not change detection thresholds, settle/anchor sequencing, saturation math structure, trigger
shape, or logging formats. I also did not build, compile, start a server, benchmark, or run tests, per
the box-owner constraint.
