# Online resharding and live migration

## What this implementation is

This resharder does not copy keys. It changes ownership of a contiguous virtual-bucket range between two adjacent workers that already alias the same physical per-node database array; `reshardArm` rejects a source and destination whose `server.ex_dbs[]` pointers differ. (`src/server.c:6108-6137`, `src/server.c:15593-15605`)

The cutover therefore consists of draining old-owner work, rewriting the bucket-to-worker table, and updating one range boundary. The coordinator's former copy-convergence, replay, reference-fence, and source-cleanup states now advance without copying or deleting data. (`src/server.c:15865-15876`, `src/server.c:16047-16083`)

Keys map to one of 16,384 buckets with `xxh64(key) & (TOMO_BUCKETS - 1)`, and routing reads the owning worker byte from `server.ex_bucket_table[bucket]`. The kvstore dictionary index uses the same bucket number. (`src/server.h:1560-1571`, `src/server.h:1599-1603`, `src/server.c:9533-9555`)

This is consequently an online, same-physical-database ownership migration, not a cross-node live data migration. (`src/server.c:15600-15605`, `src/server.c:16047-16055`)

## Core data structures

| State | Actual representation and fields | Source |
|---|---|---|
| Bucket geometry | `TOMO_BUCKETS = 16384`, `TOMO_BUCKET_MASK = 16383`; 256 load-balancer groups contain 64 consecutive buckets each. | `src/server.h:1560-1580` |
| Ownership | `uint8_t ex_bucket_table[TOMO_BUCKETS]` maps bucket to worker; `int ex_bucket_end[TOMO_EX_THREADS_MAX]` stores each worker's exclusive high boundary. | `src/server.h:3377-3381` |
| Physical databases | `node_dbs` has one database array per topology node; every `ex_dbs[w]` is assigned the array for worker `w`'s node. | `src/server.c:6117-6137` |
| Public migration gate | `_Alignas(64) _Atomic unsigned char migration_active`; it is separate from the rest of the migration record. | `src/server.h:3382-3388` |
| Migration record | Atomic `uint64_t gen`; plain `int lo, hi, src, dst`; atomic `int phase`; atomic per-producer `int fence_acked[TOMO_IO_THREADS_MAX + 1]`; atomic `uint64_t fence_gen`. | `src/server.h:3388-3399` |
| Public phase values | `MIG_IDLE=0`, `MIG_COPYING=1`, `MIG_DRAINING=2`, `MIG_FLIPPED=3`, and `MIG_DONE=5`; value 4 has no enum member. | `src/server.h:2301-2308` |
| Coordinator state | `co_state` is atomic and uses `CO_IDLE`, `CO_WAIT_CONVERGE`, `CO_WAIT_ATOMIC`, `CO_DRAINING`, `CO_WAIT_APPLIED`, `CO_WAIT_REFS`, `CO_WAIT_DONE`, and `CO_QUIESCE`. | `src/server.c:226-235` |
| Coordinator auxiliaries | Main-owned timeout/wake/abort state is `co_fence_t0`, `co_atomic_fence_t0`, `co_atomic_ref_counted`, `co_last_wake`, `co_aborted`, and `co_hb0`. | `src/server.c:15804-15817` |
| Arm serialization | `_Atomic int mig_arm_lock` serializes armers; `_Atomic uint64_t mig_arm_seq` identifies successful arms; `_Atomic uint64_t co_serving_arm` identifies the arm served by the current coordinator. | `src/server.c:15569-15584` |
| Parked clients | The server has one `clients_mig_parked[]` list per IO identity; the client tail stores `mig_parked_node` and `mig_parked_tid`. | `src/server.h:1792-1794`, `src/server.h:1852-1857`, `src/server.h:3202-3210` |
| Queue drain frontier | Each SPSC `exQueue` has consumer `head`, consumer-published `retired`, producer `tail`, producer-private `staged_tail`, and `jobs[]`; `head` and `tail` are on separate cache lines. | `src/server.h:2437-2477` |
| Fence marker | A fake client uses a non-NULL `clientTail(fake)->drain_ack` as the marker; the pointer value is not used to choose the ack slot. | `src/server.h:1778-1793`, `src/server.c:15631-15641`, `src/server.c:22096-22105` |
| Worker load signals | Each worker has atomic `ops_total`, plain `lb_grp_ops[256]`, atomic packed `lb_fine_win`, and plain `lb_fine_ops[64]`. | `src/server.h:1578-1580`, `src/server.h:2591-2606`, `src/server.h:2702-2712` |

### Initial ownership and normal routing

At initialization, `W` is the number of workers live at boot. The table assigns bucket `b` to `floor(b * W / TOMO_BUCKETS)`, while `ex_bucket_end[i]` is `ceil((i + 1) * TOMO_BUCKETS / W)`; provisioned slots above `W` receive `TOMO_BUCKETS` as both sides of their empty suffix range. (`src/server.c:5905-5929`)

For a normal key, routing computes the hash and bucket once, caches them on the client/fake, and returns the plain byte load `server.ex_bucket_table[bucket]`; `exIndexForKey` performs the same hash, mask, and table lookup. (`src/server.c:9533-9555`)

On a successful rightward move (`dst == src + 1`), the moved range must be a source suffix and the flip sets `ex_bucket_end[src] = lo`. On a successful leftward move, the range must be a source prefix and the flip sets `ex_bucket_end[dst] = hi`. (`src/server.c:15553-15565`, `src/server.c:16051-16056`)

## Range validation and arming

### `reshardRangeValid`

`reshardRangeValid(lo, hi, src, dst)` applies these predicates in order: (`src/server.c:15553-15566`)

1. `dst` must equal `src + 1` or `src - 1`. (`src/server.c:15553-15555`)
2. Source bounds are `s_lo = src == 0 ? 0 : ex_bucket_end[src - 1]` and `s_hi = ex_bucket_end[src]`; it rejects `lo < s_lo` or `hi > s_hi`. (`src/server.c:15555-15557`)
3. Moving the complete source range is rejected unless the global `tmFlipActive()` predicate is true. (`src/server.c:15558-15562`)
4. A rightward move requires `hi == s_hi`; a leftward move requires `lo == s_lo`. (`src/server.c:15563`)
5. Every table byte in `[lo, hi)` must still equal `src`. (`src/server.c:15564-15566`)

The validator itself does not check worker indexes, liveness, or `lo < hi`; its interval checks are exactly the one-sided `lo < s_lo` and `hi > s_hi` rejections above. Caller construction/validation of a nonempty interval is therefore required: manual `DEBUG RESHARD START` performs explicit range, index, and liveness checks, while internal callers construct their ranges from current boundaries. (`src/server.c:15553-15566`, `src/server.c:16676-16694`, `src/server.c:17025-17074`, `src/server.c:17110-17122`)

The whole-range exception tests only whether some thread-mode flip is active; `reshardRangeValid` does not verify that the active flip is converting this particular `src`. (`src/server.c:15558-15562`)

### `reshardArm`

Arming is a non-blocking try-lock: `atomic_exchange(..., 1, memory_order_acq_rel)` returns failure immediately if another armer or a flat resize holds `mig_arm_lock`. (`src/server.c:15572-15585`, `src/server.c:9358-9369`)

While holding the lock, `reshardArm` rejects a set flush gate with an acquire load, an active migration with an acquire load, a pending/active flat resize, or an invalid range. It then rejects different `ex_dbs[src]` and `ex_dbs[dst]` pointers. (`src/server.c:15584-15605`)

On success, publication order is: write plain `lo`, `hi`, `src`, and `dst`; release-store `phase = MIG_COPYING`; release-increment `migration.gen`; release-increment `mig_arm_seq`; release-store `migration_active = 1` last; then release-store zero to `mig_arm_lock`. (`src/server.c:15606-15623`)

`DEBUG RESHARD START` only arms the migration; `DEBUG RESHARD CUTOVER` separately starts the coordinator. The relevel, diffusion, and outlier auto-balancer paths call `reshardBeginCutover()` immediately after a successful arm. (`src/server.c:16688-16692`, `src/server.c:16759-16764`, `src/server.c:17074-17082`, `src/server.c:17106-17132`)

## Public phases as actually used

| Phase | Implemented meaning | Source |
|---|---|---|
| `MIG_IDLE` (0) | Defined by the enum, but none of the phase-transition sites stores it. After teardown, phase remains `MIG_DONE`; the teardown publishes `co_state == CO_IDLE` and `migration_active == 0`. | `src/server.h:2301-2308`, `src/server.c:15608-15611`, `src/server.c:15905-15917`, `src/server.c:15936-15945`, `src/server.c:16020-16032`, `src/server.c:16047-16057`, `src/server.c:16076-16119` |
| `MIG_COPYING` (1) | The migration is armed and its range/endpoints are published. No copying occurs; `CO_WAIT_CONVERGE` closes atomic admission and immediately moves to the atomic lifecycle wait. | `src/server.c:15608-15620`, `src/server.c:15865-15876` |
| `MIG_DRAINING` (2) | New work that is detected as touching the moving range is held, and each producer lane must be acknowledged by an executed sentinel or a dead-lane retirement proof. | `src/server.c:15696-15711`, `src/server.c:15936-16010` |
| `MIG_FLIPPED` (3) | The table and one boundary have been rewritten to `dst`; parked range commands may be retried against the new table. | `src/server.c:15724-15735`, `src/server.c:16051-16070` |
| `MIG_DONE` (5) | No copy cleanup remains. The coordinator waits for destination-worker loop quiescence before clearing `migration_active`. Abort paths also enter `MIG_DONE` without changing ownership. | `src/server.c:15905-15927`, `src/server.c:16011-16040`, `src/server.c:16076-16119` |

The normal phase path is `COPYING -> DRAINING -> FLIPPED -> DONE`. A pre-drain timeout takes `COPYING -> DONE`, and a producer-fence timeout takes `DRAINING -> DONE`; neither abort path stores `FLIPPED`. (`src/server.c:15865-15949`, `src/server.c:15905-15927`, `src/server.c:16011-16083`)

## Cutover protocol

### 1. Claim a coordinator

`reshardBeginCutover` acquire-loads `migration_active`, acquire-loads `phase`, and accepts only an active `MIG_COPYING` migration. It then CASes `co_state` from `CO_IDLE` to `CO_WAIT_CONVERGE` with acquire-release success ordering and relaxed failure ordering. (`src/server.c:16149-16155`)

If that CAS loses, the function compares the acquire-loaded current `mig_arm_seq` with `co_serving_arm` for up to 1,024 pause iterations. A match treats a repeated cutover request for the same arm as success; otherwise it increments `tomo_reshard_cutover_no_coord` and returns failure. (`src/server.c:16156-16181`)

The coordinator is a main-thread tick state machine. `beforeSleep` advances it once per event-loop pass while `migration_active` is nonzero and `co_state` is non-idle; no migration-specific thread is created. (`src/server.c:4438-4448`, `src/server.c:15804-15811`)

### 2. Close atomic-write admission before draining

In `CO_WAIT_CONVERGE`, the coordinator seq-cst stores `tomo_atomic_cutover_gate = 1`, initializes its timeout/accounting state, and release-stores `CO_WAIT_ATOMIC`; it does not scan or copy the range. (`src/server.c:15865-15876`)

Atomic write admission seq-cst checks that gate before reservation and seq-cst rechecks it after reservation. A losing post-reservation race removes both the `unsealed` and `inflight` reservations and parks the client. (`src/server.c:460-476`, `src/server.c:526-538`, `src/server.c:8363-8384`)

In `CO_WAIT_ATOMIC`, the coordinator seq-cst loads `tomo_atomic_unsealed`. Only when it is zero does it acquire-sum lifecycle references for `(src, [lo,hi))`; it remains in this state while either value is nonzero. (`src/server.c:400-408`, `src/server.c:15879-15904`)

If `reshard_fence_timeout_ms > 0` and that pre-drain wait reaches the configured duration, the coordinator increments the abort counter, marks the cutover aborted, release-stores `MIG_DONE`, release-increments `migration.gen`, seq-cst reopens atomic admission, wakes atomic waiters, and proceeds to done teardown without touching the ownership table. (`src/server.c:15905-15927`)

### 3. Publish the drain fence

The producer count is `nprod = server.io_threads + server.tm_ngrow_io`, covering main identity 0, base IO identities, and provisioned growth identities. (`src/server.c:15854-15863`)

After the atomic lifecycle reaches zero, the coordinator relaxed-stores zero to `fence_acked[0..nprod)`, relaxed-increments `fence_gen`, relaxed-increments `migration.gen`, and release-stores `phase = MIG_DRAINING` last. A producer that observes that `MIG_DRAINING` store through its acquire phase load is ordered after publication of the reset ack array and new fence generation. (`src/server.c:15936-15949`)

### 4. Hold range commands and enqueue one sentinel per producer

The normal dispatch gate first relaxed-loads `migration_active`; if nonzero, `migHoldClientIfDraining` acquire-loads `phase` and acts only when it equals `MIG_DRAINING`. This gate runs before a fake-ring slot is allocated. (`src/server.c:8328-8344`, `src/server.c:15696-15703`)

The range test is not uniformly an all-key test. If `legacy_range_key_spec.bs.index.pos == 1`, it hashes only `argv[1]` regardless of how many keys the command declares; only the other branch calls `getKeysFromCommand` and checks every returned SDS-encoded key. (`src/server.c:15674-15694`)

For a detected hit, the producer first calls `migPushFenceIfNeeded`, then records its `iotid`, adds the client once to that identity's parked list, stores the list node, sets `CLIENT_PIPELINE_STALLED`, and returns without dispatching the command. There is no read/write flag check. (`src/server.c:15696-15711`)

`migPushFenceIfNeeded` acquire-requires `MIG_DRAINING`, acquire-loads `fence_gen`, and compares it with thread-local `mig_local_fence_gen`. If the generation is nonzero and new to this producer, it creates a fake marker, sets `drain_ack` non-NULL, spin-pushes it to `server.migration.src`, then records the generation locally. (`src/server.c:15626-15642`)

`csPushSpin` uses the current `iotid`'s SPSC lane, stages the marker through `exQueuePush`, release-publishes `tail = staged_tail`, and advertises the source worker. (`src/server.c:3882-3907`, `src/server.c:12544-12586`, `src/server.c:20936-20969`)

Both `beforeSleepIO` and main-thread `beforeSleep` call `migPushFenceIfNeeded`; they call `migReleaseParkedClients` unconditionally so cleanup still runs after `migration_active` becomes zero. (`src/server.c:4387-4395`, `src/server.c:4438-4449`)

Residual internal/multi-key routing sites call `migHoldKeyIfDraining`. For an in-range key it spins until phase leaves `MIG_DRAINING`, pushes the producer fence on every loop iteration through the generation-idempotent helper, and lets identity 0 pump the coordinator. (`src/server.c:15749-15770`, `src/server.c:12648-12661`, `src/server.c:13553-13580`)

### 5. Execute and collect the drain proof

The worker acquire-refreshes a queue's published `tail`, copies a FIFO prefix, and release-advances `head` before executing that prefix. (`src/server.c:21024-21054`)

When the execution loop reaches a fake whose `drain_ack` is non-NULL, it release-stores `fence_acked[i] = 1` using the actual queue-lane index `i`, frees the marker, and emits no reply. It does not dereference `drain_ack` to select the ack slot. (`src/server.c:22073-22105`)

After every item in the popped batch has retired, the worker release-stores the post-pop `head` into `q->retired`. Thus `head == tail` means only that nothing remains to pop, while `retired == tail` means all published work on that lane has executed. (`src/server.c:21052-21054`, `src/server.c:22248-22263`)

The coordinator acquire-loads each `fence_acked[t]`. Slot 0 is always considered live; without a poly-thread context, base slots below `server.io_threads` are live; with a context, only acquire-loaded mode `TOMO_MODE_IO` is live. (`src/server.c:15835-15840`, `src/server.c:15990-16010`)

Wake passes are rate-limited to one per 500 microseconds, and each such pass wakes every unacked live producer. An unacked non-live lane receives a synthetic release ack only when acquire-loaded `retired == tail`; relaxed `head == tail` is used only to increment `reshard_fence_midbatch` when `retired != tail`. (`src/server.c:15842-15852`, `src/server.c:15985-16010`)

### 6. Abort or flip

If any producer remains pending until a positive fence timeout expires, the coordinator release-stores `MIG_DONE`, release-increments `migration.gen`, reopens the atomic gate, wakes atomic and IO producers, and leaves both `ex_bucket_table` and `ex_bucket_end` unchanged. (`src/server.c:16011-16040`)

When no producer is pending, the coordinator advances through `CO_WAIT_APPLIED`; that state has no replay wait. It writes every plain table byte in `[lo,hi)` to `dst`, updates the one shared boundary, release-stores `MIG_FLIPPED`, then release-increments `migration.gen`. (`src/server.c:16042-16057`)

After publishing `MIG_FLIPPED`, it seq-cst reopens atomic admission, wakes atomic waiters, and wakes every non-main producer so its parked-client sweep runs. (`src/server.c:16058-16070`)

`migReleaseParkedClients` returns only while phase is exactly `MIG_DRAINING`. Otherwise it removes each client from the owning identity's list, clears `CLIENT_PIPELINE_STALLED`, and calls `processInputBuffer`, so success retries against the flipped table and abort retries against the unchanged table. (`src/server.c:15714-15736`)

### 7. Finish and tear down

`CO_WAIT_REFS` immediately release-stores `MIG_DONE` and advances to `CO_WAIT_DONE`; the removed copy engine leaves no source copy or post-flip reference cleanup. (`src/server.c:16076-16084`)

The coordinator then acquire-snapshots `exThreads[dst].loop_seq`, enters `CO_QUIESCE`, and waits until that heartbeat has advanced by at least three. (`src/server.c:16087-16101`)

Teardown clears any flip-tail action, release-stores `co_state = CO_IDLE`, and only then release-stores `migration_active = 0`. This order lets a new armer that acquire-observes inactive state also observe an idle coordinator. (`src/server.c:16102-16119`)

Finally, teardown relaxed-increments `reshard_done_seq` on both successful and aborted cutovers. On a successful grow-front whose captured action is 2, it may then request the converting thread's target role. (`src/server.c:16024-16031`, `src/server.c:16120-16139`)

## The FIFO-sentinel argument and its actual boundary

Within one published `exQueue` lane, the intended proof is implemented as follows: a producer acquire-observes `MIG_DRAINING`, prevents a detected range command from being dispatched, appends one sentinel after work already staged in that lane, the source worker executes the lane FIFO, and the coordinator acquire-observes the worker's release ack before flipping. (`src/server.c:15634-15641`, `src/server.c:15696-15711`, `src/server.c:15990-16010`, `src/server.c:20936-21054`, `src/server.c:22096-22105`)

The execution-site ack is essential: `exQueuePopBatch` advances `head` before execution, so queue emptiness cannot prove that the popped batch has retired. The separate post-batch `retired` store is the code's quiescence proof for a lane with no live producer. (`src/server.c:21024-21054`, `src/server.c:22254-22263`)

That proof is not unconditional in the current implementation because admission reordering has a pre-queue TLS buffer. With `server.tomo_reorder > 0` and `server.strict_order == 0`, eligible ordinary commands are stored in `tomo_rord` before any worker-ring slot is written; the sentinel bypasses `exDispatchPush`'s drain barrier by calling `csPushSpin` directly. (`src/server.c:3505-3533`, `src/server.c:3986-4021`, `src/server.c:15634-15641`)

On IO threads, `beforeSleepIO` pushes the sentinel before `handleWorkerReplies`; `handleWorkerReplies` calls `flushExQueues`, and `flushExQueues` is what drains `tomo_rord`. An older range command can therefore still be in TLS scratch when the sentinel is published, and the later scratch drain enqueues it to the worker ID captured before `DRAINING`. (`src/server.c:3710-3748`, `src/server.c:3989-4018`, `src/server.c:4387-4411`, `src/server.c:4120-4126`, `src/server.c:20852-20861`)

The same ordering can occur when the pre-ring range gate encounters `DRAINING`: `migHoldClientIfDraining` pushes the sentinel immediately, without first draining `tomo_rord`. (`src/server.c:15696-15711`, `src/server.c:3986-4021`)

Consequently, the dispatch comment's assertion that every old-owner command necessarily lands ahead of the producer's sentinel is true for work already in the SPSC queue, but not for work still in reorder scratch. (`src/server.c:8483-8492`, `src/server.c:3505-3519`, `src/server.c:20859-20861`)

Fence generations make sentinel production idempotent, but the marker carries no generation: it contains only a non-NULL pointer, and the worker unconditionally writes the current global `fence_acked[i]`. The timeout branch does not remove queued markers, while a later drain resets the same ack array; the execution handler therefore cannot distinguish a late marker belonging to an older cutover. (`src/server.c:15630-15641`, `src/server.c:15936-15944`, `src/server.c:16011-16040`, `src/server.c:22096-22105`)

The ownership bytes themselves are plain `uint8_t` loads and stores. The flip release-stores `MIG_FLIPPED`, but routing helpers do not load `migration.gen`; normal dispatch reaches the acquire phase check only when its preceding relaxed `migration_active` load observes nonzero. (`src/server.h:3380-3399`, `src/server.c:8334-8336`, `src/server.c:9533-9555`, `src/server.c:15696-15698`, `src/server.c:16051-16057`)

## Automatic resharding (`reshardAutoTune`)

### Schedule and operator controls

`serverCron` invokes `reshardAutoTune()` in a nominal 1,000 ms period. The actual enable and significance control is `tomokv-key-lb`, stored in `server.reshard_min_ops`: 0 disables the balancer, a positive value is the minimum mean worker delta for the statistical outlier/diffusion paths, and the configured default is 20,000. Pending exact relevel work runs before that mean-floor branch. (`src/server.c:2943-2947`, `src/config.c:3292`, `src/server.h:4121-4123`, `src/server.c:16925-16927`, `src/server.c:16957-16965`)

`tomokv-reshard-fence-timeout` is a modifiable integer in milliseconds with default 10,000; zero disables both positive-timeout abort checks. (`src/config.c:3293-3303`, `src/server.c:15905-15906`, `src/server.c:16011-16013`)

### Controller state and signals

The controller keeps slow and fast per-worker EWMAs, prior `ops_total` snapshots, a primed flag, per-worker hot streaks, the peak before the last move, and a settle countdown. (`src/server.c:16189-16202`)

It lazily allocates per-worker arrays for 256 coarse group EWMAs and raw snapshots. It separately allocates a 64-bucket fine-window EWMA, raw snapshots, the selected group per worker, and warmup state; each allocation set is committed only if every array in that set succeeds. (`src/server.c:16217-16219`, `src/server.c:16247-16251`, `src/server.c:16854-16880`)

The worker increments `ops_total` by the size of each popped batch before classifying its items. For ordinary fakes with `argc >= 2`, it increments the bucket's coarse group counter and, when the relaxed-loaded packed fine window covers that bucket, its fine counter. (`src/server.c:22042-22053`, `src/server.c:22212-22230`)

The 1 Hz controller reads `ops_total` with the relaxed single-writer helper and uses an unsigned delta from the previous sample. It does not divide by measured elapsed time; its rate is the counter delta per nominal cron invocation. (`src/server.c:16882-16898`)

### Exact trigger path

1. The function returns before folding state if `reshard_min_ops <= 0`, `exThreads == NULL`, `migration_active` is nonzero, a thread-role flip is active, or fewer than two workers are live. Disabling also relaxed-disarms and frees existing fine-window state. (`src/server.c:16797-16825`)

2. Slow alpha is `clamp(previous_tick_mean_delta / (4 * reshard_min_ops), 0.05, 0.25)`. Fast alpha is `min(2 * alpha, 0.95)`; because slow alpha is capped at 0.25, the implemented fast alpha cannot exceed 0.5. (`src/server.c:16832-16849`)

3. For each live worker, the controller folds the raw delta into the slow and fast EWMAs and folds all 256 plain group-counter deltas with the slow alpha. (`src/server.c:16882-16914`)

4. The controller updates the mean-delta input for the next tick and runs the fine-window pass, which folds the previously armed window and then chooses the hottest group intersecting each live worker's range. It arms only when that group's rate is at least `max(4 * group_sum / intersecting_group_count, 0.05 * group_sum)`; an existing window remains selected unless a challenger is at least 1.25 times the incumbent or the incumbent falls below the arming bar. Only after this pass does the first invocation mark the EWMAs primed and return without evaluating a trigger. (`src/server.c:16348-16419`, `src/server.c:16915-16918`)

5. If `tm_relevel_pending` is set, exact post-role-flip releveling takes priority. It counts current table bytes, targets even per-node boundaries, treats deviations from -63 through 63 buckets as within tolerance, preserves at least one source bucket, arms at most one move per tick, and clears the flag if no boundary arms. (`src/server.c:16639-16706`, `src/server.c:16925-16927`)

6. Over live workers, the slow and fast fire bars are each `mean + max(k * sqrt(sum((worker - mean)^2) / W), 0.25 * mean)`, with `k = min(0.8 * sqrt(W - 1), 2.0)`. The slow release bar is halfway from the slow mean to its fire bar. (`src/server.c:16929-16955`)

7. Gate order is exact: mean below `reshard_min_ops` clears peak/settle and returns; `hotv <= release_bar` clears peak/settle, additively decrements that hot worker's streak, and tries diffusion; `hotv <= hot_bar` holds the streak; a positive settle counter decrements and returns; `hotv > 0.85 * mig_peak_pre` blocks progress when a prior peak exists; and the same worker's fast EWMA must exceed its fast fire bar. (`src/server.c:16957-16983`)

8. The sustain length is `K = max(3, ceil(1 / alpha))`. The code repeats the identical fast-bar test immediately before incrementing the streak, with no intervening signal update; because the first failure already returns without clearing the streak, the second failure branch that would clear it is unreachable. The current hot worker's streak must then reach `K` and is consumed before neighbor selection or planning. Streaks belonging to workers other than the current argmax are additively decremented once per tick. (`src/server.c:16515-16520`, `src/server.c:16920-16926`, `src/server.c:16981-16997`)

9. Eligible neighbors are live, immediately adjacent workers on the same topology node. If both sides qualify, the controller chooses the left only when its EWMA is strictly lower and otherwise chooses the right; the selected neighbor must also be strictly below the global live-worker mean, or the controller tries diffusion. (`src/server.c:16999-17015`)

10. `migPlanChunk` walks buckets inward from the shared boundary, never allowing the source to lose its last bucket. Its target moved load is `(Lh - Lc) / 2`; it chooses the scanned prefix/suffix minimizing `max(Lh - moved, Lc + moved)` and accepts only a reduction of at least `need_gain`. (`src/server.c:16451-16512`)

11. The outlier path sets `need_gain = 0.25 * (hot_bar - mean)`. It trusts the measured group profile only if the groups covering the source account for at least half of `Lh`; otherwise the coarse profile spreads `Lh` uniformly across the source range, with an eligible fine window still able to refine its group. (`src/server.c:16302-16325`, `src/server.c:16467-16499`, `src/server.c:17025-17036`)

12. A fine window is usable only when it is armed, fully warmed, has a positive fine-rate sum, and overlaps the source. Its per-bucket shape is rescaled to preserve the coarse group's total and is used inside that group. A zero-length plan is classified as unbalanceable and does not arm; only when fine data was used does the code run a group-only shadow plan, otherwise it assigns shadow result zero and increments the group-resolution refusal counter. (`src/server.c:16289-16325`, `src/server.c:16486-16512`, `src/server.c:17033-17066`)

13. A positive plan constructs the boundary suffix or prefix and calls `reshardArm`. On arm success it calls `reshardBeginCutover` but does not check that function's return; regardless of the coordinator-claim result, it records the pre-move hot value, sets `mig_settle = (int)(1 / alpha) + 1`, and increments the outlier fire counter. (`src/server.c:17068-17085`)

### Diffusion fallback

Diffusion is called only from the balanced/released branch and from the no-cool-neighbor branch of the outlier path. (`src/server.c:16960-16966`, `src/server.c:17013-17015`)

It scans live same-node adjacent pairs, selects the largest step whose difference is greater than `0.25 * mean` and whose high side is greater than `0.35 * mean`, applies its own 15% prior-peak and `K`-tick sustain gates, then moves an imbalance-proportional boundary range. (`src/server.c:16720-16755`)

The diffusion chunk starts as `((Lh - Lc) / (2 * Lh)) * source_range`, is raised to at least 16, then capped at half the source range or `range - 1`; a successful arm immediately starts cutover and sets diffusion settle state. (`src/server.c:16745-16765`)

## Invariants enforced by code

| Invariant | Enforcement | Source |
|---|---|---|
| Ownership-only moves | Arm refuses endpoints with different physical database pointers. | `src/server.c:15593-15605` |
| Contiguous adjacent ranges | Validation requires adjacent worker IDs, source containment, the shared boundary, and current table ownership for every moved byte. | `src/server.c:15553-15566` |
| Preserve a normal source owner | A whole-source move is rejected unless a thread-role flip is active; planners cap chunks so at least one source bucket remains. | `src/server.c:15558-15562`, `src/server.c:16454-16464`, `src/server.c:16676-16687` |
| One arm at a time | `mig_arm_lock` serializes check-and-publish, and `migration_active` rejects another active migration. | `src/server.c:15572-15592` |
| Reshard/flush/resize exclusion | Arm rejects the flush gate and pending resize; flat resize holds the same arm lock and rechecks migration/flush state. | `src/server.c:15584-15592`, `src/server.c:9325-9336`, `src/server.c:9358-9371` |
| Atomic lifecycle before range drain | Atomic admission closes while phase is `COPYING`; `DRAINING` is not published until `unsealed == 0` and source/range lifecycle refs sum to zero. | `src/server.c:15865-15945` |
| No queue-emptiness shortcut for live lanes | A live lane needs the worker's execution-site sentinel ack; a dead lane needs `retired == tail`. | `src/server.c:15990-16010`, `src/server.c:22096-22105`, `src/server.c:22254-22263` |
| Timeout never forces ownership | Both timeout branches go to `MIG_DONE` without executing the table rewrite. | `src/server.c:15905-15927`, `src/server.c:16011-16040`, `src/server.c:16047-16057` |
| Ownership publication precedes retry | Table/boundary writes precede the release store of `MIG_FLIPPED`; parked clients only retry after phase is no longer `MIG_DRAINING`. | `src/server.c:15724-15735`, `src/server.c:16051-16070` |
| Teardown publication is last | Destination heartbeat advances three times, `co_state` becomes idle, then `migration_active` is release-cleared. | `src/server.c:16087-16119` |

The invariants above do not close the reorder-scratch and generationless-marker gaps described in [The FIFO-sentinel argument and its actual boundary](#the-fifo-sentinel-argument-and-its-actual-boundary). (`src/server.c:3505-3533`, `src/server.c:15634-15641`, `src/server.c:20852-20861`, `src/server.c:22096-22105`)

## Comment/code discrepancies

| Comment or name | What the code actually does | Source |
|---|---|---|
| `MIG_COPYING` and copy-convergence prose | No key copy runs; `CO_WAIT_CONVERGE` closes atomic admission and advances. | `src/server.c:15865-15876` |
| `MIG_IDLE` phase | The enum defines it, but teardown leaves phase at `MIG_DONE` and clears only the active/coordinator gates. | `src/server.h:2301-2308`, `src/server.c:16082-16119` |
| “range WRITE,” “spin,” and “reads flow normally” immediately above the hold | `migHoldClientIfDraining` parks a detected in-range client and contains no read/write test. | `src/server.c:15644-15647`, `src/server.c:15696-15711` |
| `migAnyKeyInRange` prose says multi-key commands use the real key spec | Any command whose legacy range begins at argument 1 takes the `argv[1]` shortcut without checking its key count; only the fallback enumerates all keys. | `src/server.c:15674-15694`, `src/server.c:6392-6401` |
| Fence header says source execution decrements a `fence_count` | No fence counter is decremented; worker execution release-stores one indexed `fence_acked[i]`. | `src/server.c:15626-15629`, `src/server.c:22096-22105` |
| `reshardBeginCutover` says it spawns a detached coordinator | It CAS-arms the main-thread `co_state`; the actual coordinator is ticked from `beforeSleep`. | `src/server.c:16147-16155`, `src/server.c:4438-4448`, `src/server.c:15804-15811` |
| Producer-count prose still mentions a roughly 2 ms idle ack | Current dead-lane ack requires `retired == tail`; the timeout-based apparent-empty rule is not present. | `src/server.c:15854-15863`, `src/server.c:15985-16010` |
| Dispatch FIFO proof says all pre-sentinel work lands ahead of the marker | Work still in `tomo_rord` is not in the queue, while migration markers call `csPushSpin` directly and can be published before `flushExQueues` drains that scratch. | `src/server.c:8483-8492`, `src/server.c:3505-3533`, `src/server.c:15634-15641`, `src/server.c:20852-20861` |
| Flip prose calls the table write phase/gen-gated | Table entries are plain bytes, `migration.gen` has transition increments but routing does not load it, and the dispatch phase acquire is conditional on a relaxed active load. | `src/server.c:8334-8336`, `src/server.c:9533-9555`, `src/server.c:15696-15698`, `src/server.c:16051-16057` |
| Cron prose names `tomokv-reshard-auto` | The implementation gates on `server.reshard_min_ops`, configured as `tomokv-key-lb`. | `src/server.c:2943-2946`, `src/server.c:16797-16810`, `src/config.c:3292` |
| Balancer prose calls samples “ops/sec” | The controller subtracts consecutive counters once per nominal cron tick and performs no elapsed-time normalization. | `src/server.c:16184-16188`, `src/server.c:16882-16898` |
| Auto-trigger prose says `K` consecutive violations | Dead-band ticks preserve the current streak, and workers that lose the argmax decrement by one instead of resetting. | `src/server.c:16783-16789`, `src/server.c:16920-16926`, `src/server.c:16968-16971` |
| Auto-trigger prose describes settle as `ceil(1/alpha)+1` | The assignment is C truncation, `(int)(1.0 / alpha) + 1`; diffusion uses the same expression. | `src/server.c:16762`, `src/server.c:16973-16975`, `src/server.c:17076-17077` |
| Convergence prose says a genuinely worse new imbalance resets the chase | State records only scalar `mig_peak_pre`, not the worker identity; any later hot value above `0.85 * mig_peak_pre` takes the same no-progress return until a quiet/balanced path clears the scalar. | `src/server.c:16195-16202`, `src/server.c:16957-16979`, `src/server.c:17074-17084` |
| “Every gate” is counted | Initial off/active-migration/flip/live-count/priming exits, relevel exits, diffusion internals, and arm refusal do not increment dedicated `mig_trig` gate counters. | `src/server.c:16795-16825`, `src/server.c:16917-16927`, `src/server.c:16720-16765`, `src/server.c:17074-17085`, `src/server.c:17145-17163` |
| `reshard_done_seq` field prose describes completed moves | Teardown increments it unconditionally after either the success or abort log branch. | `src/server.h:3279-3282`, `src/server.c:16120-16127` |

## File/line map

| Area | Implementation |
|---|---|
| Bucket constants and fine-window encoding | `src/server.h:1560-1603` |
| Migration enum | `src/server.h:2301-2308` |
| Queue structure and retirement frontier | `src/server.h:2437-2477` |
| Worker load-counter fields | `src/server.h:2591-2606`, `src/server.h:2702-2712` |
| Ownership and migration fields | `src/server.h:3377-3399` |
| Balancer and fence configuration fields | `src/server.h:3279-3291`, `src/server.h:4117-4123` |
| Configuration names/defaults | `src/config.c:3292-3303` |
| Cron and event-loop integration | `src/server.c:2943-2947`, `src/server.c:4387-4395`, `src/server.c:4438-4449` |
| Reorder scratch and dispatch barrier | `src/server.c:3505-3533`, `src/server.c:3986-4021`, `src/server.c:20852-20861` |
| Initial bucket ownership | `src/server.c:5902-5929` |
| Physical database aliasing | `src/server.c:6108-6137` |
| Key-to-worker routing | `src/server.c:9533-9555` |
| SPSC push/pop | `src/server.c:12544-12586`, `src/server.c:20936-21054` |
| Range validation and arm publication | `src/server.c:15539-15623` |
| Producer marker and client hold/release | `src/server.c:15626-15746` |
| Atomic pre-drain and drain-fence coordinator | `src/server.c:15854-16045` |
| Ownership flip and teardown | `src/server.c:16047-16145` |
| Cutover coordinator claim | `src/server.c:16149-16181` |
| Auto-balancer state/profile/planner | `src/server.c:16184-16520` |
| Relevel and diffusion paths | `src/server.c:16639-16765` |
| Main auto-trigger | `src/server.c:16768-17086` |
| Debug control and observability | `src/server.c:17106-17218` |
| Worker sentinel execution and retired publication | `src/server.c:22073-22105`, `src/server.c:22248-22263` |

## Mechanisms

- [Migration drain fence](mechanisms/communication/migration-drain-fence.md)
- [Cross-node topology table](mechanisms/communication/crossnode-topology-table.md)
