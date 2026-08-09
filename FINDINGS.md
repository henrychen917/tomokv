# Flip WIP consolidation

## Result

The experiment now has exactly two historical mechanism values:

- `tomokv-flip-signal 0`: the shipping IO/EX saturation-ratio controller.
- `tomokv-flip-signal 3`: the pure worker signal with the clipped-occupancy floor repair.

They were deliberately not renumbered because existing measurements refer to those values. The
selector validator accepts exactly `{0,3}`. Values `1`, `2`, `4`, and `5` are explicit
`must_refuse` preflight cells; the only successful mechanism cells are `0` and `3`.

The corrected IO measurement is orthogonal to that choice:

- `tomokv-flip-io-wait 0` (default) selects the legacy zero-event-pass `u_io` operand.
- `tomokv-flip-io-wait 1` selects `1 - epoll_wait_us / wall_us` when supported.

The wait counter is collected and published independently of both selectors. Under either
io_uring backend, `tomokv_io_wait_supported` is `0` and a requested wait input explicitly falls
back to legacy because DEFER_TASKRUN work cannot be separated from kernel wait.

## Exactly what was deleted

- Mode 1's admitted knob value, `FLIP_SIG_WORKER` constant, retained-server-bound-gate selector
  path, documentation, and successful knob-matrix cell.
- Mode 2's admitted knob value, `FLIP_SIG_WORKER_PURE` constant, standalone pure-worker selector
  path, documentation, and successful knob-matrix cell. The pure-worker behavior needed by the
  surviving historical mode 3 remains part of mode 3; there is no separately selectable mode 2.
- Mode 4 was not present in the `2s-flip-ramp` starting tree, and none of the worker-skew branch's
  max-live-worker occupancy implementation was ported. Compatibility classifications and
  reservation text introduced by the IO-wait commit were removed; value 4 is refused.
- Mode 5's selector, constant, range admission, documentation, diagnostic identity, and successful
  knob-matrix cell. Its measurement was retained under `tomokv-flip-io-wait`; value 5 is refused.

The unmeasured mode-4 idea is retained only as history. Its stated falsifier was: if settled
ZRANGE(100), pipeline 32, at io4/ex4 shows
`tomokv_ex_occupancy_max - tomokv_ex_occupancy_mean < 0.05`, the worker-skew hypothesis is dead.
It may be revisited after the corrected `u_io` changes the picture, but it is not code in this WIP.

## Exactly what was ported from `e566c3f4f`

- Per-IO-owner `tmIoSignal.tm_wait_us`, with wrap-safe cumulative accounting.
- Nest-aware `tmIoWaitBegin` / `tmIoWaitEnd` bracketing, limited to epoll IO-owner identities so a
  nested polling yield inside a larger wait is not double-counted.
- `aeProcessEventsIO` wait-delta return plumbing. The complete non-uring `aeApiPoll` call is
  bracketed, and the adaptive drain user-poll PAUSE prefix subtracts its useful `beforesleep` work.
- IO-to-worker queue backpressure in `exDispatchDirect`, `csPushSpin`, and `csStampPush`; the
  freeback-ring wait in `freebackPush`; and every IO-owned `tomoPollingYield` call.
- Contended per-worker, commit, and MSET-pending spin locks reached by an IO owner.
- Migration drain-fence and coordinator-publication spins, FLUSH gate/control-plane waits, the
  flat-resize quiesce wait, and the IO-owned dormant-EX flat-resize `sched_yield` episode.
- Wait-state reset on IO-role entry and folding of the event-loop wait delta in `ioSlice`.
- Additive INFO fields `tomokv_io_wait_us` and `tomokv_io_wait_supported`, collected in static or
  auto mode and independently of mechanism selection.
- Per-node wait deltas and the double-precision EWMA of `1 - wait/wall`, avoiding the integer-EWMA
  truncation that pins the legacy reading at `0.97`.

No io_uring wait syscall is bracketed. With DEFER_TASKRUN, useful completion processing can happen
inside `io_uring_enter`; elapsed syscall time is not a valid wait-only measurement. Publishing
only the other uring waits would create a plausible but incomplete utilization signal, so the
unsupported zero is explicit instead.

## Control-arm confirmation

Confirmed: `tomokv-flip-signal 0` with `tomokv-flip-io-wait 0` retains the shipping controller
calculation and log bytes bit-for-bit. It selects the exact legacy
`(double)fc->io_occ_smooth / 100.0` operand, ratio direction, server-bound gate, ratio granularity
floor, anchor/sustain/throughput machinery, and empty diagnostic suffix. The new wait deltas and
EWMA are stored separately and cannot enter that decision path when the knob is off. The additive
accounting and INFO fields remain active by design so the corrected input can be compared against
the control in the same run.

Mode 3 retains its prior calculation: `-log(ex_sat)`, the pure-worker omission of the
server/client-bound gate, the worker-side granularity step, and the clipped-occupancy grow-back
floor bypass. Changing `tomokv-flip-io-wait` does not change which mechanism is selected.

The measurement motivating the fix is preserved: on ZRANGE(100), pipeline 32, io4/ex4, the legacy
zero-event-pass `u_io` pinned at `0.97`, while wait-derived `u_io` varied from `0.714` to `0.739`.
The IO threads were about 27% idle, rather than 97% busy.

Per owner instruction, no compiler, build, server, benchmark, or test was run. Review was static
only.
