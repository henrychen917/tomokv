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
