# Wave4 semantic interaction review

Reviewed against the merged production source, not just the merge conflict hunks.

| Boundary | Merged behavior and proof obligation |
|---|---|
| C2 → R1 | `FlatStore::find_notify` tests `atomic_pending_ && live != 0`, exactly as `find` does, before emitting Expired. A logical MVCC outcome therefore cannot be reclassified by `notify_flat_emit` as a physical event. Keymiss still follows the returned logical value. Reservation-only records retain ordinary physical expiry. `compat2` runs both the live predecessor witness and the reservation unit. |
| C2/R1 → NT-new-7 | `deadline_elapsed` uses `at >= 0 && at < now`; `find_notify`, `insert_notify` and `erase_notify` all call it. Equality emits no Expired. `insert_notify` and `erase_notify` report physical mutation, unlike the version-resolving read; the C2 read-only guard must not indiscriminately suppress those events. The command-clock row exercises exact deadline liveness with the existing clock double. |
| Raw overwrite → R1 | Only the observer-enabled string helper snapshots the physical expiry counter. `NotPossible` precedes memory admission, so the delta concerns the named lookup; Updated/OOM do not use the delta. `notify_overwrite_expiry` enters the same attributed sink. Clean/read-local overwrite eligibility remains unchanged. The netcmd ownership/LFU/physical-expiry assertions cover this path. |
| Mover claims → R1 | `xshard_execute` enters `NotifyExecutionScope` before dispatching either mover helper, and installs the operation-wide `PinnedNowMs`. Phase-one lookups use the notification-aware path when no version resolver is active. Phase-two list/set mutations select their notification specialization from `shard.notify_carrier()`. A destination that arrives before source publication defers before mutation; a failed source cannot insert a speculative destination. The release/acquire claim byte publishes the actual source outcome; notification retirement remains attached to the same scatter carrier. |
| Pop view → EXEC | `MoverLiveRead` changes the bare operation's read context and restores it on every exit; an EXEC child retains its parent context. Lowered element movers use `force_atomic`/`atomic_apply` and bypass the bare claim helper. This is a routing boundary, not a proof of broad EXEC conservation (see the retained moverfix counterexample). |
| Clock refresh → transactions | A new batch samples after dequeue. Scatter then reinstates `state.now_cut_ms`; MULTI/scripts retain their operation-wide pins. Expiry comparisons remain consistent within one command rather than resampling individual keys. |
| Physical events → retries/AOF | Physical records survive the existing speculative-discard sites and abort extraction; logical speculative records do not. Local script AOF fallback routes through `xshard_aof_emit_local` even with notification state attached. `notify_order`, `notify_aof` and `netcmd_units` retain their full legs. |
| Boundary fixtures | `edgetime.wait_deadline` and notification arming now wait strictly beyond the deadline. The rltopo expired fixture is 999 at now=1000, with ttl-live=1001. These preserve the original absent/live assertions. Hash-field TTL uses its separate semantics and is not globally changed to the key-expiry predicate. |

No new owner, per-owner structure, reader retry, seqlock or layout field appears
in this integration. Successful builds retain the production layout assertions.
This review does not extend the four lanes' claims to unrelated known defects.

## moverfix plain SET reachability

**None of the five PAD-patched mechanisms executes for a plain SET with
`--read-local 1` in 1s mode.** `docs/moverfix/pad_a.py` patches only the two
runtime copies of `execute_plain_element_mover` and `execute_live_pop`:

| PAD mechanism | Enclosing route |
|---|---|
| Source refresh (`xshard_peek_list`) | `execute_plain_element_mover` |
| Claim-dependent destination branches | `execute_plain_element_mover` |
| Source outcome publication (`direct_ready`) | `execute_plain_element_mover` |
| SMOVE actual-removal success | `execute_plain_element_mover` |
| Pop read-context selection | `execute_live_pop` |

The dispatch guards require phase two plus an element-mover kind, or LMPOP/ZMPOP.
SET is an ordinary single-key handler and never receives those scatter kinds;
arming the read-local lane does not change that command classification. Shared
executor/FlatStore code and text layout can affect SET, but this path analysis
does not explain or dismiss the lane's measured approximately -0.8% result.
No performance run or moverfix change is made here.
