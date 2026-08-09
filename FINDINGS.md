# Worker occupancy skew experiment

## What was added

The 4 Hz flip-controller tick now derives the raw occupancy distribution across live workers from
the existing per-worker `tm_idle_us` counters. It publishes the latest minimum, arithmetic mean,
maximum, and worker count through INFO as:

- `tomokv_ex_occupancy_min`
- `tomokv_ex_occupancy_mean`
- `tomokv_ex_occupancy_max`
- `tomokv_ex_occupancy_workers`

The same tick values are appended to the existing worker-signal log suffix as
`occ(min=... mean=... max=...)`. The values are fractions in the range 0..1, matching `u_ex`.
This adds only control-plane folding and publication; there is no new worker-path counter or write.

`tomokv-flip-signal 4` is mode 3 with one changed operand: the occupancy component of `ex_sat` is
the EWMA of the maximum live-worker occupancy instead of the EWMA of mean worker occupancy. It keeps
mode 3's worker-only signal, clip repair, queue term, anchor, band, sustain, granularity floor,
throughput judge, walk-back, and settle sequencing.

## Falsifier

If settled ZRANGE(100), pipeline 32, at io4/ex4 shows
`tomokv_ex_occupancy_max - tomokv_ex_occupancy_mean < 0.05`, the worker-skew hypothesis is **dead**.
There is no hidden hot-worker saturation for a max-based occupancy signal to recover, so mode 4
cannot explain or fix the controller's failure to prefer io2/ex6. That result should stop another
retry of this max-occupancy theory.

## Queue-depth choice

Mode 4 deliberately keeps `qd_mean`; it does not change the queue term to `qd_max`. This makes the
experiment change only the statistic named by the hypothesis: worker occupancy. Changing both
occupancy and queue statistics would make a positive or negative result ambiguous. There is also an
independent measured reason not to fold `qd_max` into this arm: the existing controller notes record
`ex_sat` swinging from 0.67 to 1.13 at the p32 optimum when max queue depth was used, repeatedly
launching climbs that throughput rejected. Removing the IO-side mean operand eliminates the old
EX-max-versus-IO-mean objection, but it does not eliminate that max-queue volatility.

## Isolation of existing modes

Modes 0, 1, 2, and 3 retain their existing decision operands and branches. The old mean-occupancy
EWMA and mean queue-depth expression remain in place and are still the only values those modes read.
Mode 0 remains the ratio control and still emits no `W(...)` suffix. Modes 1-3 gain only the requested
distribution fields in their observational `W(...)` suffix; INFO gains the additive fields above.

No build, compiler, server, benchmark, or test was run, per the measurement-box constraint.
