# Reorder and boot decisions

Entries dated 2026-11-08 transcribe rationale from the comments at lane baseline
`9a09e59190`. The original comments are undated unless stated otherwise. These
entries preserve historical evidence, not new measurements or performance claims.

## 2026-11-08 — Isolate runtime instantiations

`run_fused_server`, `run_fused_server_selected` and
`run_split_read_local_server` keep fused, priority and split read-local template
instantiations in separate translation units. The original comment on the
selector records that even a callback-only selector in the fused unit changes
its unit-wide inlining budget. The current decision is to choose the runtime at
boot outside the FIFO fused unit. No functions or includes move in this lane.

## 2026-11-08 — Select the ordinary integer-reply definition

The explicit `reply_int<Op::Sink>` instantiation in `main.cc` supplies the weak
definition selected by link order in both database variants. Its source comment
records that moving WAIT's cold reply out of the parser let the linker select
the differently inlined `xshard.o` definition, adding eleven instructions to
INCR. That historical observation is retained here without a new measurement;
instruction count alone establishes no throughput result.

## 2026-11-08 — Count workers that stop during boot

`run_fused_server` and `FusedBootGate` use one stop-aware state machine for load
and listener readiness. The original comment records a SIGTERM during lengthy
snapshot recovery hanging main when a parked worker exited without incrementing
the separate stopped-runner counter. A `GaveUp` arrival and stop-aware waits
keep termination from waiting for a worker that cannot become ready. Split
read-local boot uses the same gate; ordinary split boot uses it for IO activation.

## 2026-11-08 — Publish signal targets before installing handlers

`ScopedSignalHandlers::arm`, `on_signal` and `main` keep SIGINT/SIGTERM's default
action until initialized thread contexts can be published. The original comment
records that installing handlers before the table was ready silently swallowed
a signal during `Server::init`. Arm blocks these signals on main while it fills
the table, release-publishes the pointers/count, then installs the handlers.
Teardown installs SIG_IGN and clears the borrowed table before Server dies.

## 2026-11-08 — Keep CPU selection within discovered affinity

`pin_to` consumes CPUs from Topology's intersection with `sched_getaffinity`.
The original comment cites an earlier prototype selecting a disallowed CPU and
silently leaving the worker unpinned. The current helper still ignores the
setter's return value, so successful pinning is not established by this helper
alone; topology validation supplies its input precondition.

## 2026-11-08 — Bind listeners only after recovery

`main`, `run_fused_server` and `run_split_read_local_server` keep ownership of the
Unix pathname in `LateUnixListener`, deferring open until all shard owners have
loaded. The helper also checks non-socket and already-accepting paths. TCP/TLS
probes deliberately avoid SO_REUSEPORT so they cannot join another process's
listener group; closing the probe before worker activation leaves a concurrent
startup window. `probe_boot_listener` filters port zero; the lower-level
`make_exclusive_boot_listener` itself would bind an ephemeral port if passed zero.

## 2026-11-08 — Preserve the deterministic hash fallback

`main` replaces all three hash words only after a complete `getrandom` read.
The old comment asserted that this small read never fails on the deployment
kernels. The code establishes only that short reads and failures leave the
default deterministic hash material in place; the rewritten contract states
that narrower guarantee. Recovery may subsequently replace it with persisted
hash material before routing or loading keys.

## 2026-11-08 — Keep a bounded, fixed priority quota

`ExReorderQueues`, `ShadowReorderQueues` and `kExReorderShortQuota` use a quota of
four. The removed comment ties it to an 8:2 short/long workload, explicitly
calling it inherited fairness policy rather than a measured optimum. The
two-queue comment also left its conservative non-head classification costs for
an S4 measurement. No result for that measurement is established here. The
source retains the pick-count bound and explicitly makes no wall-time promise.

## 2026-11-08 — Keep a bounded oracle beside the indexed hint

`ShadowDispatch`'s scanning constructor remains a serverless reference for
`ShadowLongIndex`, `LazyShadowDispatch` and `ShadowDemotionDispatch`. The
production parse pass constructs its dispatcher only when a pending long
predecessor matters. Each task keeps its own predecessor distance; later longs
cannot change it. The demotion bitmap prunes completed longs but must recheck
the newest surviving predecessor on every query. This preserves the old scan's
completion observations without per-operation reader retries.

## 2026-11-08 — Preserve capability controls in the isolated runtime

`reorder_available` and `r7::shadow_available` are cold out-of-line predicates
for existing kind-A behaviour twins: FIFO or non-shadow priority behaviour with
the candidate's text size/layout. The source predicates and generated runtime
remain in place; this lane changes no control or compiler input beyond its
documented local renames. Binary identity, rather than a throughput experiment,
is the acceptance criterion for these documentation changes.

## 2026-11-08 — Capture one report for both shutdown renderers

`collect_shutdown_report`, `print_shutdown_report_human` and
`print_shutdown_report_json` share one owned value after worker join. The
original header records that the fused path previously omitted per-thread,
writeback, TLS and epoll evidence and that two independent `stuck:` walks had
diverged. `ShutdownReportFinalLine` is declared first in main so its destructor
prints the captured JSON after runtime teardown. Both output grammars stay
byte-for-byte unchanged in source literals.

## 2026-11-08 — Report lifetime work by final split role

`collect_shutdown_report` charges each split thread's lifetime `LoopSignals::ops`
to dispatched work when its final role is IO, and executed work otherwise.
This is not exact accounting across role changes. The original decision avoids
adding operation-path increments solely for shutdown attribution; the source
contract now states this limitation directly.

## 2026-11-08 — Fence issuer and coordinator cleanup separately

`IoLoop::shutdown_on_issuer` runs on the physical issuer before join, after its
snapshot and persistence guards drain. `shutdown_clients_after_join` runs on
the coordinator only after all workers join, consumes owed completions, tries
the ordered reply prefix once, exits the ring, then frees buffers and Clients.
The former file header described only the post-join stage. The revised header
documents both stages and preserves the prohibition on freeing buffers before
the kernel lifetime fence. It changes no cancellation or retirement behaviour.
