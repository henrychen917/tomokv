# Client balancing could hold read input until its five-second guard

Base: `118487882` (v3 `5d567adf5` plus gate-instrument commits only).
No server, benchmark, load generator, or gate was started by this lane.

## Exact hold

1. `Server::lb_should_pause()` returns true for the selected connection throughout
   `ClientDrain`.
2. `IoLoop::parse_and_dispatch()` returns `Progress` before parsing any buffered bytes.
3. `genthread_ifid_batch()` sees buffered input and `Progress`, then `enqueue_ifid()`
   sets the connection's `ifid_pending` bit again.
4. At the control tail, `client_transfer_ready()` rejects `client_pipeline_referenced()`
   because that bit is set. The hold prevents the parser from clearing the queued work.
   The original control tail only refused TLS, MULTI, and blocked clients immediately;
   this refusal repeated until `kMoveTimeoutNs` expired.

The regression drives those production methods with continuous arrivals. It requires an
empty ROB, unchanged receive cursor, a requeued IFID reference, and the exact readiness
error before exercising the bound. The frozen PRE fails with:

```
FAIL core concurrency: busy move MUST be refused within four passes of continuous arrivals
```

This proves a self-sustaining hold even after executor work has drained. Runtime debug
counters distinguish this predicate from protocol, deferred-output, CLIENT-state, and
executor-lifetime refusals instead of assuming every episode has the same cause.

### Stack3 control

The maintainer's `LBSTALL-BRIEF.md` reports that client-lb alone causes the stall and that
stack3 has no episodes in two runs. Comparing v3 with stack3 `147ac24b7` explains the latter:
stack3 removes the `client_pipeline_referenced()` migration check, `pending_ifid_`, and
the targeted fused IFID schedule. Its completion hook uses the ordinary active-client
path. The predicate responsible for the directed v3 failure is absent there.

This lane keeps v3's pipeline and lifetime fences. It refuses the move when they are busy.

## Change

- A source refuses every failed client readiness check immediately, including when the
  destination has not yet acknowledged. The connection resumes its existing input queue.
- A ready source can wait at most three IO control tails for destination preparation.
- Shard movement shares a three-tail budget across `IoDrain` and `ExDrain`. Every live IO
  can refuse, including a non-coordinator. A stage transition cannot renew the budget.
- Pending control tails report work, so a drain does not sleep waiting for the guard.
- Refusal, drain advancement, client-start, and shard commit serialize on the existing
  shape-transition mutex. A refusal cannot resume dispatch during a shard ownership edge.
- Refused candidates enter the existing cooldown filter. The five-second guard remains.
- A `ClientMoving` transfer retains its kernel-pointer fence; preflight refusal cannot
  revoke a transfer after asynchronous receive cancellation has started.

The new budget and diagnostics live in the existing LB-only policy allocation. Both LB
knobs at zero allocate no policy or stall state. Stable control tails return before all
new accounting. The normal parser and executor operation paths have no new counters.
The bound counts IO control tails, not wall-clock microseconds: an operation already
executing in a pass retains its existing service cost.

## Diagnostics

`INFO`'s existing LB section includes `tomokv_lbstall_pipeline`, `protocol`,
`deferred_output`, `client_state`, `executor`, `invalid_client`, `destination`, and
`pass_limit`, plus `pending_ns_max`. Normal builds count the successful bounded refusals.
`pending_ns_max` is request-publication to refusal, an upper bound on a buffered frame's hold.

`TOMO_LB_STALL_DEBUG` additionally instruments the already-taken parse hold. Its counters
are `parked_passes`, `parked_bytes_max`, and `parked_ns_max`; the latter measures first to
latest observed park on an owner in the movement epoch. For a client move that owner has
exactly one selected connection. It is an observed span, not an end-to-end latency metric.
`tomokv_lbstall_debug` identifies whether that instrumentation was compiled in.

The diagnostic-only `TOMO_LB_STALL_OBSERVE_ONLY` build disables the new refusals and counts
predicate observations until the old timeout. It allows the maintainer to attribute a
five-second episode with the same debug instrumentation. It is never a runtime option.

## Verification and controls

The `route` selection in `tests/core_concurrency_unit.cc` now also covers continuous
arrivals, destination non-acknowledgement, unfinished executor scopes, refused and
successful shard plans in both modes, a live non-coordinator, simultaneous commit/refusal,
and the allocation-free disabled controller. It preserves the original route-order test.
These checks use actual queues and production methods; no socket or ring is initialized.

The existing `core concurrency route` row is emitted by `job_core_units` above the quick
exit (`tests/gate.sh` lines 1227–1246; collected at line 2640; quick exit at line 2747).
No row was added or retired. Counts stay **419 quick / 436 full**. Neither EXPECT constant
nor any gate source was changed.

### Additional failures reproduced on PRE

- `atomic-survivors-unit post_apply_probe`: two completed APPENDs after first-owner APPLY
  both return length 2 and leave `BW`, violating the probe's legal serial outcome. The
  source explicitly marks this probe as outside the green gate (`tests/atomic_survivors_unit.cc`,
  `post_apply_probe`, and `FIXES.md`).
- `netcmd-unit collection-oom`: the existing OPEN F05 probe reports that failed multi-field
  HSET retains a changed prefix and its previous TTL (`tests/netcmd_unit.cc`, `collection_oom`).

Both failures were reproduced using the frozen PRE source and production objects and have
identical POST diagnostics. They are reported here because they violate the correctness
contract; this lane does not change those command mechanisms.

Final artifact digests, compiler-body comparison, and test totals are recorded in
`MEASURE-REQUEST.md`. Raw logs and the frozen PRE objects are in `build/lbstall-proof/`.

### Code-generation limits

GCC 13.3's cold-code inlining changes initially altered reply/executor bodies. The two
Makefile translation-unit budget locks retain those v3 bodies. The offline comparison
now finds 359/363 raw matches and 361/363 matches after resolving address relocations.
It checks parser, dispatch, executor, reply, and GET/SET/MGET/MSET bodies, including the
runtime reorder-off and reorder-on branches. It does not execute either server mode.

The remaining two names alias one 513-byte read-local conflict helper in `genthread.o`,
under `parse_and_dispatch<true,32,...>` (`NoBorrow=true`, the TLS specialization). At byte
offsets 282 and 302, `66 39 70 22` becomes `66 3b 70 22`: the equality compare's operands
are commuted. Both sites feed only JE/JNE before flags are overwritten. No length,
instruction count, load, or branch changes there. This is still a strict byte mismatch;
the checker deliberately returns failure and records it in `encoding-exceptions.json`.

The IO control-tail body itself changes, including its compiler-generated prologue
(stack reservation 0x268 to 0x278). Its stable branch does not call the new accounting,
but it is not byte-identical machine code. `lb-control-bodies.txt` records both versions.
Accordingly this lane does **not** claim whole-program byte identity or measured zero
regression. POST/PAD and the maintainer's matched-load gate are needed for that verdict.
