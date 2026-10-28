# Validation history retained

- The first directed run used a RESP reader that did not accept null bulk replies.
  Oracle and candidates all failed the empty unsubscribe check. The reader now
  accepts `$-1`, while retaining exact frame comparisons. This was a test bug.
- An intermediate Tcl run passed every promoted pubsub/tracking assertion in
  both modes but failed unrelated 1s slowlog-rewrite and blocked BRPOPLPUSH/WATCH
  assertions. The receipt is retained under `proof/superseded-post2`. The final
  Tcl jobs are rerun without simultaneous lane builds; no skip was added.
- The first gates_test run rejected the new eviction source path outside the
  instrumented core/cmd source globs. Moving the file to src/cmd restored
  instrumented builds. Text/rodata/data were identical across that move.
- The second gates_test run hit a one-slot scheduler fixture timeout (124)
  while builds were running. Its complete failure log is retained. A later
  standalone run is required; the timeout was not widened.
- One directed redirect timed out in the intermediate POST. Code inspection
  found a pass-boundary hazard: BCAST flushed before local notification events
  were drained, then the pending flag could be cleared with BCAST keys still
  queued. The final order drains first, then flushes BCAST. A deterministic
  serverless negative control with the old order fails the new assertion;
  POST passes. `proof/post-interrupted-redirect` retains the interrupted run.
- The initial header eviction helper changed DB0 atomic MSET inlining by +64
  instructions per command. The final out-of-line source restores all 52
  command/read-local comparisons to exactly PRE. Superseded counts remain.

These earlier failures are not counted as successful final proof. The merit
report records the final gate results separately, including any remaining
failures; there is no performance result in these receipts.
