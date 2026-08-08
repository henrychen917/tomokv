# THredis/TomoKV flip-pool conservation findings

Scope: branch `2s-flip-poolfix`, starting at `3c0a608d6`. I changed only actuator, role-transition,
accounting, and observability code. `tomoFlipController()` decision/detection math, settling,
anchoring, saturation, and triggers are unchanged.

## Exact break

At the starting HEAD, the grow-back accounting was split across two independent state machines:

1. `tmFlipTick()` observed that the IO thread had adopted EX and decremented
   `io_threads_live` at `src/server.c:22094`.
2. It later set the process-global `tm_mig_flip_action = 3` at `src/server.c:22124`; that latch was
   the only authority for the matching `num_workers_live++` in the reshard coordinator at
   `src/server.c:14722-14729`.
3. If the seed migration's producer drain fence timed out, the coordinator deliberately cleared
   `tm_mig_flip_action` at `src/server.c:14676-14682`, because an unperformed ownership FLIP could
   not publish its old action-3 liveness side effect.
4. Teardown still published `migration_active = 0`. Grow-back phase 2 then took its ordinary
   completion path at `src/server.c:22136-22143` and released `tm_flip_ctx`, with no remaining code
   able to perform the worker increment.

That path is a persistent **loss of one**: `io_threads_live--` lands, `num_workers_live++` is erased,
and the first quiescent controller tick reports the observed 7/8 pool.

The full starting-HEAD write audit found no current double-increment path: action 3 was evaluated
once in `CO_WAIT_APPLIED`, which immediately advanced to `CO_WAIT_REFS`. Also, role conversion has
no `pthread_create`; the only two calls in `server.c` are boot-time pool creation (now at
`src/server.c:21358` and `src/server.c:21463`). The quoted `2-balancer tasks 10 -> 11` row belongs to
the retired PARKED/spare controller: this branch's `tools/preflight/controller_sweep.sh:768-774`
explicitly deletes that section and points its replacement at `flip_updown.sh`. Therefore the
current live-counter defect is a loss, not a gain. Removing action 3 also removes the only decoupled
grow-back increment, so a stale coordinator latch cannot manufacture a gain in the fixed design.

I found a second grow-back actuator race adjacent to the loss. The timeout path first loaded
`target_mode != EX` and then published IO-EXIT CANCEL, while the IO owner independently stored
`target_mode = EX`. The owner could commit between those operations; main would release the flip as
"aborted" while the thread adopted EX. The raw sum could still look correct, but the roles and the
two counters described different threads.

## Fix: explicit claim -> convert -> publish

The live-count updates are now owned by one flip-accounting transaction
(`src/server.c:21918-21985`):

- Grow-front records an outstanding EX claim before its required early worker delist. Successful IO
  adoption publishes the destination and clears the claim. Every error/release path restores the
  claimed EX source via `tmFlipAccountingRollback()`; `tmFlipRelease()` has a final rollback hook at
  `src/server.c:142-151`, so a newly added early return cannot leak the claim.
- Grow-back does not change either live count while IO-EXIT is merely draining. Once `mode == EX` is
  release-published, `tmFlipAccountingPublishEx()` performs the complete `io-- / worker++` move in
  one non-returning helper (`src/server.c:21976-21985`, called at `src/server.c:22206-22215`). The
  optional bucket seed owns no live counter.
- The reshard coordinator no longer increments `num_workers_live`. A seed-fence abort now leaves an
  already-published, empty-but-live EX worker; phase 2 records the recovery and completes normally
  (`src/server.c:22254-22268`). Thus reshard success, refusal, retry, or abort cannot suppress or
  duplicate either half of the role move.
- Grow-back commit versus timeout cancellation is a CAS state machine. The IO owner claims
  `DRAINING -> COMMITTED` before requesting EX (`src/server.c:22872-22899`); the watchdog competes for
  `DRAINING -> CANCEL_REQUESTED` (`src/server.c:22179-22202`). If cancellation wins, main holds the
  flip claim until the owner has successfully rejoined the accept group and published
  `ROLLED_BACK` (`src/server.c:22748-22777`, consumed at `src/server.c:22153-22168`). A failed listener
  rejoin retries and cannot falsely acknowledge rollback.

Conservation follows from the terminal states:

- grow-front claim -> IO publish, or grow-front claim -> EX rollback;
- grow-back draining -> cancel/IO rollback with counts untouched, or commit -> paired IO-to-EX move;
- seed outcome -> no accounting operation.

There is no quiescent release with an unpaired source claim, and there is no longer a reshard-side
worker increment that can be lost or applied twice.

## Recovery counter and guard

I added the atomic file-global cumulative counter `tomo_flip_recoveries`, exported in `INFO stats` as
`tomokv_flip_recoveries` at `src/server.c:17925-17930`. It increments for every abandoned/rolled-back
conversion and for a grow-back whose seed cutover is abandoned but safely completed empty-live.
It is file-global because the flip actuator is control-plane-only; it is atomic because INFO may be
served by an IO thread while the actuator/coordinator increments it.

The existing `POOL BROKEN` check remains a rate-limited `LL_WARNING`, not an assertion, at
`src/server.c:23438-23478`. Its `io_live_node` off-by-one explanation is intact at
`src/server.c:23457-23461`: poly IO slots exclude main/iotid 0, while the invariant continues to use
raw `io_threads_live + num_workers_live`.

## Static verification only

- Audited every `io_threads_live` / `num_workers_live` occurrence under `src/`; after initialization,
  every write is centralized in the accounting helpers.
- `git diff --check` passes.
- Per instruction, I did not compile, start a server, run a benchmark, or run any test.
