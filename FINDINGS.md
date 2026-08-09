# IO wait-time saturation signal

## Result

The new per-IO-owner `tm_wait_us` counter measures wall time spent waiting rather than inferring
idleness from an event-loop pass that returned zero events. `INFO` publishes the live-role sum as
`tomokv_io_wait_us` and publishes `tomokv_io_wait_supported` so an io_uring run cannot mistake an
unsupported zero for a fully busy reading.

The current tree defined modes 0-3, while the adjacent worker-skew branch already owns mode 4.
Mode 5 is therefore the new experiment: it keeps the mode-0 IO/EX saturation ratio, but substitutes

```
u_io_tick = 1 - mean_per_thread(wait_us_delta / wall_us)
```

for the IO utilization operand. A double-precision EWMA at the controller's existing
`FESC_ALPHA` rate feeds the ratio, avoiding the integer-EWMA truncation that can pin the legacy
value at 0.97. Modes 0-4 retain their existing decision paths; this pre-worker-skew branch keeps
mode 4 rejected rather than reassigning it, and the combined tree admits worker-max mode 4 plus
IO-wait mode 5. Mode 0 also retains its existing `[flip-ctl]` bytes because the new diagnostic
suffix is empty there. The wait counter itself is collected independently of selection, so two
INFO snapshots can observe old and new counters while mode 0 remains the decision control.

Merge note: when the worker-skew commit is combined, its mode-4 implementation and `try 4` matrix
cell replace this branch's explicit reserved-value rejection; the mode-5 range, selector, and
`try 5` cell remain.

## Wait regions bracketed

- The complete non-uring `aeApiPoll` call. On Linux this covers `epoll_pwait2`/`epoll_wait` for
  indefinite idle polls, converted-thread bounded polls, zero-timeout drain passes, and the 100 us
  drain fallback. Event callbacks execute after the bracket closes, so event handling is not
  charged as wait.
- The adaptive drain user-poll PAUSE prefix. Its total span is measured and the individually timed
  `beforesleep` calls are subtracted because those calls drain completed replies and are useful
  work.
- IO-to-worker queue backpressure in `exDispatchDirect`, `csPushSpin`, and `csStampPush`, plus the
  freeback-ring wait in `freebackPush`.
- Every `tomoPollingYield` call. Server-side brackets are nest-aware, so the yield inside an
  already-bracketed queue wait does not double-count time.
- Contended per-worker, commit, and MSET-pending spin locks reached by an IO owner.
- Migration drain-fence and coordinator-publication spins, FLUSH gate/control-plane waits, and the
  flat-resize quiesce wait.
- The `sched_yield` path reachable from an IO-owned dormant EX slice: the flat-resize episode is
  bracketed as a whole. The other `sched_yield` belongs only to live-worker idle backoff under the
  current slice policies and is deliberately not charged to IO.

The server-side helper records only identities in the IO slot range. Worker PAUSE/yield backoff,
the never-adopted thread's startup `clock_nanosleep`, restart delay, synchronous replication
`aeWait`, and the worker-only FLUSH barrier were audited but are not live IO-loop wait time and are
not charged.

## io_uring / DEFER_TASKRUN

Neither io_uring backend is bracketed. With DEFER_TASKRUN, useful completion processing can run
inside `io_uring_enter`; elapsed syscall time therefore cannot be split into sleep and work. This
is the exact mechanism behind the recorded false `io_sat=0.17` reading on a 99.5%-CPU thread.

Mode 2 has a poll-on-ring-fd fallback on old kernels that is individually measurable, but counting
only that fallback and the server-side spin waits would publish a partial metric as if it were a
complete utilization estimate. That was rejected. Both uring modes instead leave `tm_wait_us` at
zero, report `tomokv_io_wait_supported:0`, and make flip-signal 5 explicitly log `UNSUPPORTED` and
fall back to the unchanged mode-0 operand.

## Expected falsifier reading

At ZRANGE(100), pipeline 32, io4/ex4, 200 connections on epoll, a mode-5 `[flip-ctl]` suffix has:

```
IW(sig=5 wait_us=<delta>/<thread-wall> u_io_idle=<legacy> u_io_raw=<tick> u_io_wait=<EWMA>)
```

`u_io_idle` is still derived from `tm_idle_us` and is expected to remain near the observed 0.97.
`u_io_raw` and `u_io_wait` should be materially below 1.0 and should move across ticks if the IO
threads spend substantial time in poll/drain waits. The ordinary `S(... u_io=...)` field is the
selected mode-5 wait-time value, so `io_sat` and the ratio use the same number the suffix exposes.

If both wait-derived values remain near 1.0, the IO threads really are saturated under this
definition. In that result the old signal was directionally right, and the io2/ex6 optimum needs a
different explanation; the patch intentionally does not bias or reinterpret that outcome.

## Rejected estimators and limitations

- Scheduled thread CPU was not reused: polling/drain spin consumes CPU while no useful IO work is
  available and therefore over-reports busy.
- Zero-event episodes remain published only as the legacy control: one event makes a whole pass
  busy and therefore under-reports wait under continuous arrivals.
- Whole `io_uring_enter` elapsed time was not used for the DEFER_TASKRUN reason above.
- Wait is folded when a bracket closes. A wait spanning a controller boundary can therefore make
  adjacent raw ticks lumpy; per-thread clamping and the existing EWMA bound the decision input,
  while cumulative INFO deltas remain wrap-safe. No poll timeout was changed merely to force a
  metric fold, because doing so would alter the IO policy being measured.
- IO slot 0 remains excluded from controller means and the INFO live-role aggregate, matching the
  existing signal: main runs `aeMain`, not `ioSlice`, and is structurally outside the measured poly
  IO pool.

Per instruction, no compiler, build, server, benchmark, or test was run. Review was static only.
