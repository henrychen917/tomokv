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

- A cross-feature probe found that the first implicit-consumer fix also emitted
  a tracking invalidation. Redis and PRE emit none when only consumer metadata
  changes. The final helper emits keyspace notifications and SAVE observations
  without the tracking route or WATCH mutation. The directed case now witnesses
  all implicit events, requires tracking silence, then uses a real XADD to prove
  that the same tracking connection is armed. The earlier binary is retained as
  `plants/tomokv-consumer-tracking` for a directed negative control.
- One intermediate directed run successfully evicted `foo`, acknowledged
  `CONFIG SET maxmemory 0`, returned DBSIZE 0, then OOM-rejected SET of the empty
  key. The complete wire transcript is retained in
  `proof/superseded-eviction-rearm` and extracted into
  `maxmemory-reset-observation.json`. A 128-cycle CONFIG 1/0 + SET probe on Redis,
  PRE and POST in both modes did not reproduce it (`config-zero-audit.json`).
  Attribution is therefore unresolved. The existing owner-local memory-policy
  cache refreshes at pass entry; this code is unchanged by the lane. Each key's
  eviction is now armed on a fresh server, so the row independently proves both
  ordinary and empty keys without depending on a previous reset. The failed
  reset observation remains an open finding, not a passing result.

- A final Redis-source audit found that a whole-cache invalidation leaves the
  per-prefix BCAST key sets intact. The candidate incorrectly cleared pending
  keys. A deterministic unit queues key invalidation and whole-cache invalidation
  in the same pass: the earlier binary fails; the correction emits null followed
  by the sorted key array (`bcast-flush-control.json`). The earlier full affected
  run is retained as `proof/post-before-flush-preservation` (228 passes).
- The accompanying live probe (`bcast-flush-audit.json`) also records inherited
  differences: PRE and the earlier candidate reject FLUSHDB inside MULTI, and
  their SET/FLUSHDB pipeline produces a key push before the null push, while
  Redis produces null then the key push. A TCP pipeline does not establish a
  common event-loop pass across these different execution architectures. The
  unit explicitly establishes that pass boundary; this lane does not broaden
  transaction command admission or claim identical pass partitioning.
