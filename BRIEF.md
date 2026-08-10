P0 WEDGE CONTRIBUTOR (proven; do not re-derive): when a frozen QSBR grace
finally advances, flatWorkerReclaim (src/server.c ~8737) drains the ENTIRE
ready prefix of the worker's batch list inside one exSlice pass, and each
freed batch runs its payload callbacks (flatRetirePayloadReady), including
tomoVersionPruneAfterGrace full-bag walks. With tens of thousands of matured
batches this freezes the worker's dispatch-ring pop loop for seconds; pending
cross-shard write subs sit unpopped (witnessed via gdb: 32 published entries
unconsumed, every stuck group at pending=1), which is the other half of the
atomic-write collapse. flatReclaimAll (~8816, main/beforeSleep) has the same
unbounded shape.

DELIVERABLE — BUDGETED RECLAIM DRAIN (fix B):
1. Bound the work done per pass in BOTH flatWorkerReclaim and flatReclaimAll:
   drain at most BUDGET batches per invocation, leaving the rest for the next
   pass. The pop loop must regain control in bounded time regardless of
   backlog depth.
2. BUDGET must guarantee CONVERGENCE while backlogged: drain strictly faster
   than production. Self-derive it — e.g. budget = 2 * batches_closed_since_
   last_pass_on_this_thread + 4 — rather than a bare constant; no new config
   knob. Document the convergence argument in a comment.
3. Preserve the FIFO prefix property (oldest-first; stop at first non-ready).
4. Witness: a counter (INFO: tomokv_flat_reclaim_budget_trips or similar)
   incremented whenever a pass stops on budget with ready batches remaining —
   proves the mechanism engaged during validation.
5. Zero behavior change when the backlog is small (budget never binds on the
   healthy path); no new allocation; minimal diff.
