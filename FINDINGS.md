# Productive-work saturation ratio

## Result

Ratio modes now compare the same physical quantity on both roles:

```
u_io = delta(io productive-work us) / (wall_us * n_io_live)
u_ex = delta(ex productive-work us) / (wall_us * n_ex_live)
r    = u_io / u_ex
```

Both raw fractions use one node-local controller snapshot span, the exact live-role count for that
span, and the same double-precision `FESC_ALPHA` EWMA. Backlog-augmented saturation remains the
server/client-bound gate and the worker-only signal, but it is no longer divided to make ratio-mode
`r` or used to price the ratio floor.

`tomokv-flip-signal 5` is the default productive-ratio spelling. Mode 0 remains accepted as a
deprecated compatibility alias and reaches the exact same non-worker branch; it can no longer
select zero-event IO occupancy. Modes 1, 2, and 3 retain their existing worker idle-plus-queue
signals and gates.

## Productive spans counted

The IO numerator counts only explicitly bracketed application work in `aeProcessEventsIO`:

- The pass prefix: initial io_uring CQ harvest/ready-parser callbacks, when enabled, followed by
  the normal `beforeSleepIO` callback. `beforeSleepIO` covers pending connection data, worker-reply
  retirement, stalled-client release, pending reply writes, migration service, and async frees.
- Every `beforeSleepIO` call made inside the bounded adaptive-drain user-poll prefix. The existing
  per-call brackets now contribute to `tm_work_us` instead of being used only to subtract work from
  wait.
- The post-poll fired-event span: readable callbacks (receive, parse, and dispatch) and writable
  callbacks.
- The io_uring post-enter CQ harvest/ready-parser span and its ready-only native-epoll handoff,
  including the callbacks that handoff discovers. The nonblocking native probe is included because
  it runs only after a CQ explicitly reports `AE_URING_EPOLL_READY`; it is not an empty drain poll.

The EX numerator is the existing `tm_busy_us` interval from first work pop through work-pass end.
Its deliberately excluded background expiry/reclaim work remains excluded.

The following are deliberately not IO work: ordinary blocking, bounded, and zero-timeout
`aeApiPoll` calls; `io_uring_enter` (sleep and DEFER_TASKRUN are indivisible there); the PAUSE-only
portion of adaptive drain; event-loop policy bookkeeping outside callbacks; the outer poly-thread
checkpoint; dormant-EX safety slices; and the main thread's generic `aeMain` loop. IO slot 0
therefore remains outside both the numerator and the movable-IO denominator, matching the existing
granularity floor. The sole `aeApiPoll` exception is the ready-only io_uring handoff listed above.

## Clock cost and spin exclusion

An event-bearing epoll work pass adds two net vDSO reads, matching the worker work-pass budget:
the productive prefix adds two, the event-work start reuses the existing poll-return timestamp,
and its end is the per-pass timestamp formerly read by `ioSlice`, moved rather than added. A
zero-event epoll pass is net +1 because it reuses the poll endpoint and removes that old caller
read. Adaptive-drain work reuses its existing epoll brackets. The io_uring path is net +3 on an
ordinary pass because it needs one additional post-enter boundary; adaptive-drain callback
brackets are also new there. Those boundaries are required to avoid classifying the indivisible
enter or PAUSE spin as work.

Empty-poll spin cannot inflate `tm_work_us`: PAUSE instructions, ordinary zero-timeout/short drain
polls, and backend waits are outside the productive brackets. The ready-only io_uring native probe
cannot be entered by an empty poll; a CQ must first report native readiness. The sampled IO
thread-CPU counter is still published as `tomokv_io_busy_us`, but it is not a controller input.

## Observability retained

`INFO` now publishes `tomokv_io_work_us`. The existing `tomokv_ex_busy_us` is the symmetric EX
work counter. `tomokv_io_wait_us`, `tomokv_io_wait_supported`, `tomokv_io_idle_us`,
`tomokv_ex_idle_us`, and scheduled-CPU `tomokv_io_busy_us` remain available for comparison; none
selects a ratio-mode operand. Ratio log lines include raw work numerator/denominator pairs, raw and
smoothed role fractions, `r`, and the legacy idle/wait observations.

## Required falsifier

The productive metric passes only if `r` is near 1 at every one of the 15 measured static-sweep
optima and moves away from 1 at their neighbours. The specifically required cells are:

| workload | optimum | old r at optimum | required productive r | neighbour requirement |
|---|---:|---:|---:|---|
| GET p32 | io4/ex4 | 1.23 | about 1 | io5/ex3 moves away from its old false 1.00 |
| MGET8 p32 | io4/ex4 | 1.31 | about 1 | io5/ex3 moves away from its old false 1.01 |
| GET p1 | io7/ex1 | already near 1 | stays near 1 | adjacent splits are not nearer |
| MGET8 p1 | io6/ex2 | 1.04 | stays near 1 | adjacent splits are not nearer |
| ZRANGE p1 | io5/ex3 | 1.09 | stays near 1 | adjacent splits are not nearer |

If the two p32 relationships do not reverse, or any p1 optimum moves materially away from 1, the
definition is falsified and must not be tuned to resemble success.

Per instruction, no compiler, build, server, benchmark, or test was run. Review was static only.
