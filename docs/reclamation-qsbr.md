# QSBR memory reclamation

## What the implementation protects

The flat table publishes each slot as one atomic 64-bit word. A lookup acquire-loads that word and can return the encoded `kvobj` pointer, while overwrite and delete replace the word with release stores and return the old pointer to their caller. The old allocation therefore cannot be destroyed merely because the slot no longer names it. (`src/flatstore.c:207-215`, `src/flatstore.c:269-293`)

The reclamation layer turns removed pointers into `flatRetireNode` records, closes records into FIFO `flatBatch` objects, and releases a batch only after its foreign-thread, dispatch-group, IO-epoch, and worker checks all pass. Releasing a record either decrements an ordinary object, invokes a version-prune callback, or frees detached version metadata, depending on two tag bits carried in the record's pointer. (`src/flatstore.c:25-51`, `src/server.c:8955-9000`, `src/server.c:9016-9077`)

Replaced `flatTable` allocations do not use the per-batch test. They are kept in a separate retired-table array and freed only on a pass that observes no foreign reader, no odd IO epoch, and no worker inside a flat section. (`src/server.c:9147-9178`)

## Protocol state

### Reader and batch state

| State | Actual fields and layout |
| --- | --- |
| IO epoch | The QSBR portion of each cache-line-aligned `tmIoSignal` is `_Atomic uint64_t flat_epoch` followed by padding to the end of that cache line; the process has `tm_io_sig[TOMO_IO_THREADS_MAX + 1]`. (`src/server.c:649-667`, `src/server.c:776-789`) |
| External-reader TLS | `flat_extern_depth` is the nesting depth; `flat_slot_owned` is the registered IO slot or one of the worker/none sentinels; `flat_epoch_slot` latches the slot used by the outermost entry; `flat_epoch_val` remembers the published odd value; and `flat_foreign_held` records use of the global fallback pin. (`src/server.c:1073-1080`) |
| Unregistered-reader fallback | `flat_foreign_active` is a cache-line-isolated `_Atomic int`; a nonzero value blocks every batch-readiness decision. (`src/server.c:977-983`, `src/server.c:1151-1161`, `src/server.c:9031-9032`) |
| Worker quiescence | Each `exThread` has atomic `in_flat_section` and `loop_seq`. Its owner-private reclaim state is `flat_retire_local`, FIFO `flat_batches_local`/`flat_batches_tail`, `flat_batch_spare`, and `flat_batch_spare_n`, separated from the two polled atomics by padding and checked by compile-time cache-line assertions. (`src/server.h:2607-2613`, `src/server.h:2654-2677`, `src/server.c:1037-1043`) |
| Dispatch-group pin | Each `flatGroupPinSlot` isolates atomic `active` on its own cache line, pairs atomic `floor` with atomic `scan_lock` on the next, and separates `pin_out[4096]`; `flat_group_pin_mask.bits[]` identifies slots with active pins. `flat_batches_closed_n` is also the close-generation source, while `flat_batches_freed_n` and `flat_pin_wrap_blocks` are counters. (`src/server.c:985-1015`) |
| Pin owner record | The fake client carries `tomo_read_snapshot_gen` and `tomo_read_snapshot_pinned`; the same client also carries the read snapshot protected by the pin. (`src/server.h:1909-1924`) |
| Retire record | `flatRetireNode` contains exactly `masked_kv` and `next`. (`src/flatstore.h:67`) |
| Closed batch | `flatBatch` contains `head`, `close_gen`, `nworkers`, `next`, and flexible array `arr[]`. (`src/flatstore.h:98-104`) |
| Table-owned fallback queues | `flatTable` contains atomic `retire_stack` plus FIFO `batches` and `batches_tail`, in addition to its slots, size/mask, counters, generation, and resize request. (`src/flatstore.h:106-117`) |

The flexible `flatBatch.arr` is interpreted as three consecutive regions: `snap[flat_batch_slots]`, `io_snap[flat_batch_slots]`, and `io_pin[flat_batch_mask_words]`. Initialization sets `flat_batch_slots = server.io_threads + server.num_workers + 1` and `flat_batch_mask_words = ceil(flat_batch_slots / 64)`, and allocation uses `sizeof(flatBatch) + (2 * flat_batch_slots + flat_batch_mask_words) * sizeof(uint64_t)`. (`src/server.c:8944-8967`, `src/server.c:22816-22827`)

The worker-local list is not keyed by table: when `flat_local_sink` is nonnull, `flatRetirePayload` does not use its `flatTable *t` argument, so one worker batch can contain payloads retired from multiple flat tables. A converted IO role explicitly requests a dormant EX slice when either its retained local list or worker FIFO is nonempty. (`src/flatstore.c:168-185`, `src/server.c:21752-21775`, `src/server.c:23424-23450`)

### Version-retirement state

`tomoRetireState` has exactly three values: `TOMO_RETIRE_ACTIVE`, `TOMO_RETIRE_PRUNE_GRACE`, and `TOMO_RETIRE_PHYSICAL`; stamp state is independently `PENDING`, `APPLIED`, or `CANCELED`, and `TOMO_VERSION_UNCOMMITTED` is `UINT64_MAX`. (`src/object.h:117-127`, `src/object.h:180`)

The complete `tomoVerMeta` layout is atomic `commit`; atomic `stamped_head`; atomic cached `read_head`; `install_order`; `origin_client_id`; `reclaim_bytes`; `version_order`; `install_owner`; `install_bucket`; `version_tombstone`; `version_reservation`; atomic `version_canceled`; `stamp_state`; `retire_state`; `detached`; `lifecycle_ref_held`; atomic `read_gate`; atomic `owner_ops_pending`; `version_prev`; `stamped_prev`; `version_kvs`; `version_db`; `reservation_owner`; and owner-local `owner_next`. Every installed version's `commit` points to its group's reference-counted shared timestamp record. (`src/object.h`)

Metadata and chain access is published rather than plain: `kvobjVmeta`, the shared timestamp helpers, and both predecessor getters use acquire loads, while the corresponding metadata and predecessor setters use release stores. (`src/object.h`)

New version metadata comes from a bounded install-worker fixed-size pool, initializes null commit and cached-read pointers, a closed `read_gate`, and `version_canceled`, and inherits the unordered stamped-index head through an acquire load. An atomic install initializes `stamped_prev` and `stamped_head = self` before the vmeta/table-head release publication, starts in `APPLIED` and `TOMO_RETIRE_ACTIVE`, and records its physical predecessor, already-resolved bucket, kvstore, and database. Before publishing a successor, installation permanently supersedes the old physical head's gate. `csMsetRecordInstall` later release-attaches the shared commit record while still under the destination owner lock. Final same-owner QSBR retirement recycles the block; low-water trimming and non-owner/quiescent fallback bound or bypass the pool. (`src/db.c`, `src/object.c`, `src/server.c`)

## Reader protocols

### IO and other non-worker regions

The IO constituency is the inclusive range `0..min(server.io_threads + server.tm_ngrow_io, TOMO_IO_THREADS_MAX)`. Slot registration asserts that the slot is in this range and that the thread is outside every external region; worker registration makes the thread use the worker protocol instead. (`src/server.c:1082-1103`)

The main thread registers IO slot 0 during initialization, and a polymorphic thread registers its IO slot or the worker sentinel when it adopts that role. Both role-change sites assert zero external nesting before changing identity. (`src/server.c:5931-5936`, `src/server.c:23260-23267`, `src/server.c:23364-23366`)

`flatExternEnter` increments `flat_extern_depth` and does nothing else for a nested entry. On an outermost registered IO entry it computes `(relaxed_load(flat_epoch) | 1) + 2`, latches the slot and value, stores the resulting odd value with `memory_order_seq_cst`, and then executes `FLAT_PUBLISH_FENCE()`; that macro is empty on x86 and a seq-cst thread fence elsewhere. (`src/server.c:1105-1114`, `src/server.c:1125-1139`)

`flatExternExit` decrements the depth and publishes only on the outermost exit. For a registered IO slot it release-stores `flat_epoch_val + 1`, which is even, then clears the latched slot; worker entries publish no IO epoch. (`src/server.c:1125-1149`)

Thus odd values are the executable inside-state and even values are the outside-state. Each ordinary outer entry publishes a new odd value strictly greater than the prior value, and a nested enter/exit pair changes only the TLS depth. (`src/server.c:1125-1149`)

Starting from the zero-initialized slot, ordinary outer transitions are `0 -> 3 -> 4 -> 7 -> 8 ...`: entry is not a simple increment, because it uses `(current | 1) + 2`. (`src/server.c:1130-1148`)

An outer entry with no registered slot increments `flat_foreign_active` seq-cst and logs once; its outer exit decrements the counter seq-cst. This path never writes another thread's IO epoch. (`src/server.c:1127-1129`, `src/server.c:1151-1161`)

`FLAT_EXTERN_REGION()` uses a cleanup guard around `flatExternEnter`/`flatExternExit`, and the exported `flatQsbrRegionEnter`/`flatQsbrRegionExit` wrappers use the same depth-nested TLS state. `call()` uses the guard, while the flat arm of `dbScan` explicitly uses the wrappers. (`src/server.c:1163-1173`, `src/server.c:7187-7189`, `src/db.c:4361-4380`)

### Worker regions

At the start of every `exSlice` pass, the worker relaxed-loads `loop_seq`, adds one, and release-stores the new value. If flat shared node databases are enabled, it then points `flat_local_sink` at that worker's `flat_retire_local`, performs any node-pool trim, and runs `flatWorkerReclaim`. (`src/server.c:21781-21817`)

After that reclaim call, the worker seq-cst stores `in_flat_section = 1`. While resize is active it repeatedly stores 0, waits, and stores 1 before rechecking; the function's single return path seq-cst stores 0. (`src/server.c:21819-21842`, `src/server.c:22361-22364`)

### Dispatch-lifetime GROUP pins

A group pin is entered only for atomic mode, a cross-shard route, and either a read-only command or an admitted atomic read. The pin is established before the fake client acquire-loads the encoded commit clock once into `tomo_read_snapshot`. (`src/server.c`)

Entry takes `scan_lock` with an acquire CAS, relaxed-increments `active`, and, on the `0 -> 1` transition, relaxed-sets the slot's global mask bit followed by a seq-cst fence. It then relaxed-loads the current close counter as `gen`, stores `floor = gen` when this is the first active pin, relaxed-increments `pin_out[gen & 4095]`, records the generation and pinned flag on the fake client, release-unlocks `scan_lock`, and executes the publish fence. (`src/server.c:1175-1200`)

Exit executes a release fence, relaxed-decrements the generation cell, release-decrements `active`, and release-clears the mask bit when the old active count was one; both decrements assert a positive old count. The terminal fake-client paths clear the pinned flag and call this exit helper before recycling the fake. (`src/server.c:1202-1216`, `src/server.c:4045-4049`, `src/server.c:4200-4207`, `src/server.c:4320-4338`)

Unlike the external epoch exit, group-pin exit resolves `flat_slot_owned` at exit rather than storing an IO slot in the fake. Connection migration admits a client only after `dispatchid == flushid`, a fence whose implementation requires all dispatched fakes to have retired before handoff. (`src/server.c:1202-1206`, `src/server.h:1909-1924`, `src/server.c:23859-23868`, `src/server.c:23905-23915`)

`flatGroupPinsBlock(close_gen)` seq-cst loads each mask word and fails closed if it cannot acquire an engaged slot's `scan_lock`. Once locked, it acquire-loads the current close counter and `active`, relaxed-loads `floor`, computes ring pressure as `cur < floor || cur - floor >= 4096`, advances `floor` across acquire-loaded zero generation cells (or sets it to `cur` when inactive), and release-publishes the new floor before unlocking. Ring pressure increments `flat_pin_wrap_blocks` and blocks; absent pressure, an active slot blocks exactly when `floor <= close_gen`. (`src/server.c:1218-1253`)

Consequently, while its floor remains generation `g`, a live pin blocks batches whose `close_gen` is `g` or greater and does not block an older batch whose generation is below `g`. (`src/server.c:1192-1196`, `src/server.c:1232-1250`)

## Retirement, batch close, and grace determination

### Enqueue

`flatRetirePayload` ignores a null payload, reuses a node from the thread-local pool or allocates one, and stores the payload in it. With `flat_local_sink` set it prepends to the worker's plain local list; otherwise it pushes onto the table's atomic Treiber stack using a relaxed initial load and a release CAS with relaxed failure ordering. (`src/flatstore.c:168-185`)

Ordinary records carry the masked flat pointer. Special records set bit 63, with bit 62 additionally selecting a metadata-free record; the encoder asserts that the original pointer has neither bit set. (`src/flatstore.c:25-40`, `src/flatstore.c:187-197`)

### Close

On a worker pass, the ordinary/post-unlink list and the successful owner-epoch list are closed into
independent oldest-first FIFOs. Each lane contributes at most one header. When both are nonempty,
one fence and one fetch-add reserve both batch-count generations and the two headers share the final
grace target; splitting eligibility therefore does not add another global close RMW. (`src/server.c`)

The main-thread fallback first relaxed-peeks at each table's `retire_stack`, acquire-exchanges a nonempty stack with null, closes the returned list, and appends the batch to that table's FIFO. `beforeSleep` calls `flatReclaimAll` only when shared node databases are enabled. (`src/server.c:9181-9210`, `src/server.c:4438-4460`)

`flatBatchCloseTarget` executes the mandatory seq-cst fence, adds the number of headers being closed
to `flat_batches_closed_n` in one seq-cst RMW, and returns the final scalar grace target.
`flatBatchCloseAt` reuses or allocates each header and assigns that target. Reader entry publishes
its active state before sampling the same generation; `flatGraceAdvance` folds active IO/worker
generations into the cached scalar safe frontier. (`src/server.c`)

### Exact ready predicate

A batch is ready only if this code reaches the final `return 1`. (`src/server.c:9016-9058`)

```text
foreign_active != 0                         -> not ready
flatGroupPinsBlock(close_gen)                -> not ready
for each bit t captured in io_pin:
    current flat_epoch[t] == io_snap[t]      -> not ready
for each w in [0, nworkers):
    loop_seq[w] >= snap[w] + 2               -> this worker passes
    otherwise in_flat_section[w] == 0        -> this worker passes
    otherwise                                -> not ready
all checks passed                            -> ready
```

The foreign load is seq-cst, each selected IO epoch is acquire-loaded, each worker sequence is acquire-loaded, and the fallback `in_flat_section` load is seq-cst. `FLAT_QSBR_MARGIN` is the constant 2 used only by the worker sequence clause. (`src/flatstore.h:69-71`, `src/server.c:9016-9058`)

The foreign counter has no batch snapshot or generation: any foreign reader that is active at readiness time blocks every batch, including batches closed before that reader entered. (`src/server.c:1151-1161`, `src/server.c:9031-9032`)

An IO identity that was even at close has no bit and is never examined for that batch. An identity captured odd stops blocking as soon as its epoch differs from the captured odd value, whether it merely exited or exited and entered another region. (`src/server.c:8986-8997`, `src/server.c:9036-9044`)

A worker passes by either of two independent branches: its sequence reached the captured value plus two, or its current section flag is zero. The loop covers `b->nworkers`, which close set to `server.num_workers`, rather than filtering by a live-worker predicate. (`src/server.c:8963-8967`, `src/server.c:9045-9057`)

### FIFO drain, payload release, and budget

Atomic mode keeps the validated `flatDrainReadyBatches` path. It examines only the ready FIFO
prefix and acquire-loads the applicable frontier for each head. A ready head with zero budget
returns the budget-trip signal, while a positive budget pops the head, fixes a now-empty tail,
frees the batch, and decrements the budget. (`src/server.c`)

With atomic mode off and no owner epoch left from a live disable, workers instead use
`flatWorkerReclaimOff` and `flatDrainReadyBatchesAt`. An empty pass returns before close/frontier
bookkeeping. A nonempty pass acquire-loads the physical and logical safe frontiers once and reuses
that snapshot for its FIFO prefix. The frontiers are monotone, so this may defer a concurrently
ready batch until the next pass but cannot free a batch early. The main/table fallback uses the
same OFF-only rule. (`src/server.c`)

A non-ready head stops only that FIFO. The main nested table scan continues to later tables unless a ready head reports budget exhaustion. (`src/server.c:9095-9105`, `src/server.c:9211-9219`)

Both modes dispatch every payload, recycle retire nodes up to `FLAT_NODE_POOL_CAP` (4096), and
either retain a batch header in a worker spare list up to `FLAT_BATCH_SPARE_MAX` (8) or free it.
Atomic mode retains the validated relaxed `flat_batches_freed_n` increment per header. Atomic-OFF
drains count completed headers locally and publish one relaxed increment per drain span. This is
telemetry only; neither grace controller consumes the freed counter. (`src/flatstore.h`,
`src/server.c`)

Payload dispatch decrements the object reference for an ordinary record, releases reclaim and shared-commit accounting before an atomic object free, releases the shared-commit reference before a metadata free, and calls `tomoVersionPruneAfterGrace` for a version-prune record. (`src/flatstore.c`)

The reclaim budget is exactly zero on arithmetic overflow and otherwise `2 * closed + 4`. The
worker's physical and logical FIFOs each get budget 4 without a close or 6 after their one possible
lane close. The main path uses one budget derived from the number of table-stack batches it closed
during that scan. (`src/server.c`)

Both worker and main paths relaxed-increment `flat_reclaim_budget_trips_n` only when a ready head is deferred for lack of budget. Main returns immediately on such a drain result; if its budget reaches zero without that result, it rechecks table heads once to detect a head that became ready during the scan. (`src/server.c:9128-9131`, `src/server.c:9211-9231`)

Atomic successful-prune epochs use a second FIFO in the lazy per-worker owner state. Its batches use
the same physical grace controller and reclaim-budget function but additionally test the MVCC
snapshot frontier. The ordinary worker FIFO contains post-unlink frees and canceled owner epochs and
is drained independently. Thus a non-ready logical head stops only the logical FIFO; it cannot
convoy allocator-facing physical frees. No limit or grace rule was removed. (`src/server.c`)

## Version pruning and the two-grace path

### Arming the first grace

Every atomic install inherits its physical predecessor's authoritative stamped index and initializes
itself as the new stamped-index head before publishing the vmeta/table head. It then appends itself
to the stable owner record and release-initializes `owner_ops_pending` to one before the owner's acquire-release
`shards_remaining` decrement. The common marker is still zero, so the eager entry is invisible.
The last owner publishes the shared `commit_ts` marker and encoded global clock. (`src/server.c`,
`src/db.c`)

The same stable owner record remains on that worker's private list. A later slice freezes the
published commit frontier; when the record's marker is nonzero and no newer than that frontier, one
tagged retire node carries the complete record to the worker's separate logical FIFO. The batch
close supplies one common physical grace and its scalar maximum timestamp supplies logical
eligibility. There is no per-version first-grace node, cross-core retirement job, or reserved lane.
(`src/server.c`, `src/flatstore.c`)

Cancellation marks the eagerly indexed entry canceled and moves `ACTIVE -> PRUNE_GRACE` while the
common marker remains zero. Its owner-record payload enters the ordinary physical-grace lane with
no logical timestamp, so it cannot queue behind a successful epoch held by an old snapshot.
(`src/server.c`, `src/db.c`)

### First-grace callback

When an owner-epoch batch becomes ready, `flatBatchFree` opens one worker QSBR/lock scope and payload
dispatch calls `tomoVersionPruneOwnerAfterGrace` for each record. That callback walks the stable
owner chain, release-stores each `owner_ops_pending` from one to zero, establishes the anchor's
first-grace state, and calls `tomoVersionPruneAfterGrace`. One outer scope is shared by all records
and versions in the batch. (`src/server.c`, `src/flatstore.c`)

At callback entry, the code acquire-loads the anchor metadata, derives the executing owner from `iotid`, runs `tomoAtomicOwnerCheck`, and asserts the owner range. That check is telemetry only: on an install/current/executing-owner mismatch it relaxed-increments a stale-owner counter and returns, after which the callback continues. (`src/db.c:1144-1151`, `src/server.c:411-425`)

The callback seq-cst publishes `in_flat_section = 1`, backs out to zero and quiesces while resize is active, republishes one, and then takes the executing worker's lock. Every exit goes through `tomoVersionPruneFinish`, which unlocks, releases the callback metadata's lifecycle reference, and finally seq-cst clears `in_flat_section`. (`src/db.c:1134-1163`, `src/server.c:387-397`)

The callback branches as follows. (`src/db.c:1144-1405`)

1. Null metadata or an anchor already in `PHYSICAL` state finishes without walking a bag. A detached anchor must be in `PRUNE_GRACE`; it is reset to `ACTIVE`, passed to physical retirement, and then finished. (`src/db.c:1165-1177`)
2. A live anchor is resolved to the current table head under the worker lock. The callback acquire-loads that head's unordered stamped-index head. A canceled anchor has no timestamp and licenses only canceled nodes whose own grace is complete; an applied anchor uses its own `(commit_ts, version_order)` rank. Neither mode reads a global cursor, and both require `owner_ops_pending == 0` on the anchor. (`src/db.c`)
3. During the physical-chain scan, a canceled node is eligible exactly when it is `ACTIVE` and has zero pending owner operations. For an applied anchor, an applied version is eligible only when its nonzero shared rank is below the anchor's rank; a raw tail has implicit rank zero. Higher timestamps and zero-timestamp versions survive. (`src/db.c`)
4. An eligible interior node is removed by a release predecessor store; an eligible head advances local `newhead`. A node with no pending owner maintenance enters physical grace immediately. A lower committed node whose owner-local retirement remains pending is instead marked detached: the successor's completed grace licenses unlink, while the later owner pass retains ownership until it can schedule post-unlink grace. (`src/db.c`)
5. The callback stable-filters the unordered stamped index for both anchor kinds. A metadata-bearing
   node survives exactly when it is `APPLIED`, not detached, and not `PHYSICAL`. A canceled anchor
   retains a raw predecessor because cancellation does not license retiring it; a successful anchor
   drops the raw predecessor it retired during the physical scan. Survivor links are release-stored
   and the new tail is terminated with null. (`src/db.c`)
6. If no physical survivor remains, the callback deletes the key through `dbSyncDelete` and finishes. Otherwise it release-stores the repaired stamped-index head into a versioned new head, or asserts that a raw head equals that index head. After publishing a changed physical head, it re-censuses that bag and release-opens the new head's key-local read gate only when no unfinished conflicting group remains. (`src/db.c`)
7. If the physical head changed, the callback release-overwrites the flat slot, then repoints, removes, or adds the whole-key expiry entry according to the old and new heads and replaces their hash subexpiry membership. (`src/db.c:1290-1320`, `src/flatstore.c:269-275`)
8. The survivor census counts a raw node as committed and stops; ignores canceled nodes; counts a version as uncommitted when its shared timestamp is zero or its stamp is not `APPLIED`; and counts every other version as committed. (`src/db.c`)
9. With exactly one committed survivor and no uncommitted survivor, a metadata-bearing tombstone is deleted when it is the callback anchor, is `ACTIVE`, or is in `PRUNE_GRACE` with no lifecycle reference—the state left when its callback record was discarded. The callback resets `PRUNE_GRACE` to `ACTIVE` before `dbSyncDelete`. (`src/db.c:1345-1372`, `src/flatstore.c:54-68`)
10. With exactly one committed survivor, no uncommitted survivor, and no physical predecessor below the sole committed object, a metadata-bearing non-tombstone is promoted when it is the callback anchor or has no lifecycle reference. Promotion requires an applied stamp and zero pending owner work, release-stores the stamped index to self, releases exact per-owner byte accounting, release-detaches the metadata, and queues that metadata for grace-delayed commit-reference release and free. (`src/db.c`, `src/flatstore.c`)
11. If none of the terminal branches returned, an anchor still in `PRUNE_GRACE` is reset to `ACTIVE` before the common finish path. (`src/db.c:1403-1405`)

### Physical retirement and the second grace

For an object with metadata, `tomoSchedulePhysicalRetire` requires either `stamp_state == APPLIED` with a nonzero shared timestamp, or `stamp_state == CANCELED` with no timestamp, and an acquire load must see zero pending owner operations. An already-`PHYSICAL` metadata-bearing object returns without another enqueue; otherwise the helper writes `PHYSICAL`, and either that object or a metadata-free input is queued once as an ordinary raw retire record. (`src/db.c`)

For a still-live bag, its owner-epoch record waits for the pre-unlink grace while the anchors remain
table-reachable. Ready dispatch invokes the local callbacks without freeing an anchor; under the
worker lock, they unlink eligible objects and enqueue ordinary records rather than freeing them.
(`src/server.c`, `src/flatstore.c`, `src/db.c`)

For an applied or raw node below the anchor rank, that pre-unlink grace can be supplied by the local successor's callback: the applied-node eligibility branch does not require the selected node's own retire state to be `ACTIVE`. If its owner-local retirement is still pending, the node is detached and waits for that pass before physical grace. A canceled node is different because its eligibility explicitly requires `ACTIVE`, which its own callback establishes only after its tagged grace matures. (`src/db.c`)

Owner-local post-marker maintenance runs on the install worker while `exSlice` has armed `flat_local_sink`; on this path, `flatWorkerReclaim` closes and clears the existing local retire list before it drains ready batches. A raw retire created by a prune callback during that drain therefore lands in the now-empty local list, cannot be part of the batch invoking the callback, and is closed with a fresh snapshot on a later worker pass. (`src/server.c`, `src/flatstore.c`)

That later close executes the seq-cst pre-snapshot fence after the completed callback and its unlink work. The ordinary record's later ready dispatch releases exact reclaim bytes and the version's shared commit-record reference, then calls `decrRefCount`; object destruction also frees attached `vmeta`. (`src/server.c`, `src/flatstore.c`, `src/object.c`)

For an eligible interior node, the release predecessor unlink occurs before its ordinary enqueue. For an eligible physical head, the callback enqueues the raw record while scanning and release-overwrites or deletes the flat slot later; the later-pass close rule above makes the new batch's fence and snapshots occur after the entire callback, including that delayed head unlink. (`src/db.c:1233-1239`, `src/db.c:1269-1292`, `src/server.c:8969-8997`, `src/server.c:9113-9131`)

The detached-before-callback case is the explicit exception to two new graces because the table
unlink has already happened. The owner epoch still owns the allocation through
`owner_ops_pending`; when its first-grace callback runs, the detached branch schedules the object
directly into the ordinary post-unlink lane. (`src/server.c`, `src/db.c`)

Removing a whole version bag marks every metadata-bearing member detached. A raw tail is ordinary-retired immediately; a canceled member or one with a nonzero shared timestamp is physically retired when pending owner work is zero and state is `ACTIVE`; a `PRUNE_GRACE` member waits for its already-armed callback; a `PHYSICAL` member already has retire work; and a genuinely pending/uncommitted member or one with nonzero `owner_ops_pending` waits for terminal owner work. (`src/db.c`)

Table discard is terminal for the retire record, not necessarily for its version. Because table teardown/replacement is already quiescent, discard decrements ordinary records and releases commit references before freeing atomic objects or metadata, but suppresses a pending prune callback, releases only its install-owner lifecycle reference, and leaves the version's `PRUNE_GRACE` state unchanged. It applies this dispatch to both the table stack and table-owned closed batches; a later sibling callback recognizes the no-lifecycle `PRUNE_GRACE` state in its tombstone-deletion and live-promotion branches. (`src/flatstore.c`, `src/db.c`)

## Replaced-table reclamation

After resize copying completes, the code release-publishes the new table, appends the old table pointer to `flat_retired_tables`, seq-cst clears `flat_resize_active`, and resumes the normal state machine. (`src/kvstore.c:78-86`, `src/server.c:9431-9447`)

Within `beforeSleep`, value reclaim and the retired-table check run before the resize coordinator, so a table appended by that coordinator is first considered by `flatRetiredTablesTryFree` on a later `beforeSleep` pass. (`src/server.c:4438-4460`, `src/server.c:9431-9447`)

`flatRetiredTablesTryFree` returns if the array is empty, if the seq-cst foreign count is nonzero, if any IO epoch seq-cst load is odd, or if any worker's seq-cst `in_flat_section` load is nonzero. Otherwise it calls `flatTableFree` for every accumulated table and resets the count to zero; it does not consult batch snapshots, close generations, or the group-pin mask. (`src/server.c:9166-9178`)

`flatTableFree` first uses the quiescent discard path for table-owned pending records and batches, then frees the slots and table allocation; it deliberately does not free the live objects that were copied to the replacement table. (`src/flatstore.c:96-107`, `src/flatstore.c:123-128`)

Worker-local retire lists and batches are not members of the old table and are not visited by `flatTableFree`; they remain on their worker's reclaim state. (`src/flatstore.h:98-117`, `src/server.h:2654-2677`, `src/flatstore.c:168-185`)

## Atomic-ordering inventory

| Edge | Ordering implemented in code |
| --- | --- |
| Flat slot read/unlink | Lookup loads the slot with `memory_order_acquire`; overwrite and delete publish the replacement/tombstone with `memory_order_release`. (`src/flatstore.c:207-215`, `src/flatstore.c:269-285`) |
| Shared retire stack | Fallback enqueue uses a release CAS; main takes a list with an acquire exchange. (`src/flatstore.c:181-184`, `src/server.c:9181-9188`) |
| Worker announcements | `loop_seq` is release-stored and acquire-loaded by close/readiness; `in_flat_section` transitions and readiness loads are seq-cst. (`src/server.c:9045-9055`, `src/server.c:21790-21798`, `src/server.c:21827-21841`, `src/server.c:22361-22364`) |
| IO announcements | Entry uses a relaxed prior-value load, seq-cst odd store, and architecture-dependent publish fence; exit uses a release even store; close seq-cst snapshots epochs and readiness acquire-loads only captured slots. (`src/server.c:1105-1114`, `src/server.c:1125-1149`, `src/server.c:8993-8997`, `src/server.c:9036-9043`) |
| Foreign pin | Entry/exit RMWs and readiness load are seq-cst. (`src/server.c:1151-1161`, `src/server.c:9031-9032`) |
| Batch boundary | Close executes a seq-cst fence, then a seq-cst generation fetch-add, then acquire worker snapshots and seq-cst IO snapshots. (`src/server.c:8969-8997`) |
| Group pin | Scan-lock acquisition is acquire and release-unlock; first-active mask publication is relaxed plus a seq-cst fence; generation cells are relaxed-updated and acquire-scanned; active exit and last-active mask clearing are release operations. (`src/server.c:1178-1215`, `src/server.c:1220-1250`) |
| Owner-local lifetime | `owner_ops_pending` is release-initialized to one after install-side index publication and release-stored to zero by the owner-epoch callback before pruning; no cross-core queue publishes it. (`src/server.c`) |
| Prune worker lock | The callback's worker lock is acquired by a strong CAS with acquire success/relaxed failure and released by a release store. (`src/server.c:9668-9684`, `src/db.c:1134-1163`) |
| Version links | Metadata, commit pointer/timestamp, and both predecessor getters are acquire; setters are release. The callback also release-publishes the repaired stamped-index head. (`src/object.h`, `src/db.c`) |

## Enforced invariants

- Only the outermost external scope publishes or clears an IO epoch, and registration asserts that identity does not change while the nesting depth is nonzero. (`src/server.c:1091-1103`, `src/server.c:1125-1149`)
- Registered IO entry always publishes an odd value greater than the value it loaded; registered IO exit publishes the following even value through the entry-latched slot rather than re-resolving thread identity. (`src/server.c:1130-1149`)
- An unregistered thread cannot alias slot 0: it uses the global counter, and any nonzero counter makes every batch fail readiness. (`src/server.c:1127-1129`, `src/server.c:1151-1161`, `src/server.c:9031-9032`)
- A batch cannot free while a captured IO slot still contains the exact odd epoch seen at close; an IO slot that was even at close is omitted from that batch's mask. (`src/server.c:8986-8997`, `src/server.c:9036-9044`)
- Every provisioned worker must either advance by the margin of two or currently publish `in_flat_section == 0`; worker liveness is not a bypass. (`src/server.c:8963-8967`, `src/server.c:9045-9057`)
- Group-pin scanning fails closed on scan-lock contention, close-generation wrap/underflow pressure, or an oldest live generation not newer than the batch. (`src/server.c:1218-1253`)
- Retire FIFO mutation is oldest-first, and draining never walks beyond the first non-ready batch. (`src/server.c:9095-9105`, `src/server.c:9115-9125`, `src/server.c:9188-9192`)
- A live version moves `ACTIVE -> PRUNE_GRACE` before its callback record is queued. A selected metadata-bearing node with no pending owner maintenance is marked `PHYSICAL` before its one ordinary record is queued; one awaiting owner-local retirement is only detached until that pass. A selected raw tail has no retire-state transition, and an already-`PHYSICAL` metadata-bearing input returns without another record. (`src/db.c`)
- On the owner-worker/local-sink path, the live-bag version path cannot physically destroy an object in the first callback batch: callback-created raw records enter the local list after that list was closed and are snapshotted on a later pass. (`src/flatstore.c:168-180`, `src/server.c:9113-9131`, `src/db.c:1233-1239`)
- The prune callback performs live-bag traversal while both the worker flat-section announcement and the worker lock are held, and it drops the lifecycle reference only after unlocking. (`src/db.c:1134-1163`)
- Replaced table allocations are freed only when the current foreign/IO/worker scan is entirely outside; their test is separate from the batch-ready predicate. (`src/server.c:9147-9178`)

## Code/comment discrepancies

- The comment above `flatRetire` says the owning worker pushes a Treiber stack and main closes/reclaims it, but executable worker retirement is a plain local-list prepend followed by same-worker close and drain; only the no-local-sink fallback uses the table Treiber stack and main path. (`src/flatstore.c:130-132`, `src/flatstore.c:168-185`, `src/server.c:9108-9132`, `src/server.c:9181-9233`)
- The introductory reclaim comments describe a main-thread, worker-`loop_seq` grace, but the ready function also gates on the global foreign pin, group generations, captured IO epochs, and each worker's section flag. (`src/flatstore.c:14-20`, `src/server.c:8931-8937`, `src/server.c:9016-9058`)
- The batch-close fence comment says every payload was first unlinked by `flatOverwrite` or `flatDelete`. A version-prune payload is intentionally queued while its anchor remains live, and a metadata payload follows `kvobjSetVmeta(..., NULL)` rather than a flat-slot unlink; the close fence is real, but that universal provenance statement is not. (`src/server.c:8969-8977`, `src/db.c:1089-1105`, `src/db.c:1393-1398`, `src/flatstore.c:191-197`, `src/object.h:219-225`)
- Two comments give fixed batch-size estimates of approximately 816 bytes and 544 bytes. The allocation is runtime-sized by `sizeof(*b) + (2 * flat_batch_slots + flat_batch_mask_words) * 8`, so neither fixed estimate defines the live layout. (`src/server.c:8936-8961`, `src/server.h:2671-2677`, `src/server.c:22823-22826`)
- A compile-cap comment says the batch IO snapshot/mask uses `TOMO_IO_MASK_WORDS`, while the batch macros and allocation use runtime `flat_batch_mask_words`; the fixed-size mask is used by `flat_group_pin_mask`, not by `flatBatch.arr`. (`src/server.h:1470-1479`, `src/server.c:1004-1010`, `src/server.c:8944-8961`)
- Comments equate `flat_batch_slots` with the largest reachable `io_hi + 1`, but allocation uses the conservative `server.io_threads + server.num_workers + 1`, whereas the reader bound uses the current `server.tm_ngrow_io` and the compile-time cap. (`src/flatstore.h:87-97`, `src/server.c:1082-1089`, `src/server.c:8944-8953`, `src/server.c:22823-22826`)
- The batch-close comment says `nworkers` is defensively clamped, but the executable assignment is exactly `int nw = server.num_workers; b->nworkers = nw;` with no clamp branch. (`src/server.c:8963-8967`)
- The node-pool comment says retire nodes never outlive the batch that frees them, but `flatBatchFree` retains freed nodes in the TLS pool until later reuse or trimming, so a recycled node can outlive that batch header. (`src/flatstore.c:134-156`, `src/server.c:9061-9077`)
- The non-live-worker note claims at most the final pass plus two ungraced batches remain, but no FIFO-length branch enforces two: a worker can append one batch per pass while any foreign, group, IO, or worker readiness clause keeps the head blocked. Dormant converted threads do continue servicing nonempty reclaim state, but that is a progress path rather than a two-batch cap. (`src/server.c:9031-9058`, `src/server.c:9113-9144`, `src/server.c:21752-21775`, `src/server.c:23424-23450`)
- The `flat_local_sink` comment says it is null on non-worker threads, but the role-conversion path sets the TLS pointer during EX operation and handles retained reclaim state through dormant EX slices while that same OS thread is in the IO role; no role-transition store clears the sink in this path. (`src/flatstore.h:73-83`, `src/server.c:21752-21775`, `src/server.c:21800-21816`, `src/server.c:23260-23267`, `src/server.c:23424-23450`)
- The version-retirement overview says pruning removes versions below the committed maximum, but an applied callback uses the callback anchor's sequence as `retire_max`; the current global committed value is an exclusion/census bound, not the prune frontier. The same callback also has a canceled-anchor mode. (`src/db.c:922-926`, `src/db.c:1187-1206`, `src/db.c:1212-1231`)
- The detached-bag comment says uncommitted members remain pinned, but a canceled member also retains the uncommitted sentinel and is immediately eligible for physical scheduling when it has zero pending owner work and is `ACTIVE`; only members failing the executable terminal/pending/state condition wait. (`src/db.c:1108-1111`, `src/db.c:1121-1130`)
- The promotion comment calls the result a raw-head fast path, but the promotion condition requires only that the sole committed object's own `version_prev` be null. Canceled nodes above it are ignored by the census, so the table's physical head can still be a canceled metadata-bearing node until its callback prunes it. (`src/db.c:1322-1343`, `src/db.c:1375-1401`)
- The retired-table comment says at most a couple of tables can be pending, but the implementation grows `flat_retired_tables` dynamically from capacity 8 and imposes no executable count bound. The resize state-machine comment also says it frees the old table at swap, while the code appends it for later all-readers-outside reclamation. (`src/server.c:9147-9165`, `src/server.c:9237-9248`, `src/server.c:9431-9447`)
- Normal drains increment `flat_batches_freed_n` per header in atomic mode or once by the completed
  span count in atomic-OFF mode, but quiescent table discard frees table-owned closed batches
  without incrementing it. Therefore the INFO expression `closed - freed` can retain discarded
  batches rather than being an exact queue length. (`src/flatstore.c`, `src/server.c`)
- Comments that list KEYS and RANDOMKEY as inline readers are stale: KEYS is registered as `CS_RT_FANALL` and dispatched to worker subs, while RANDOMKEY is in the worker whitelist and has a worker-selection branch. (`src/server.c:1045-1050`, `src/server.c:9147-9151`, `src/server.c:9383-9387`, `src/server.c:10803-10804`, `src/server.c:13742-13792`, `src/server.c:8828-8830`, `src/server.c:9472-9477`)

## File map

| Area | Implementation |
| --- | --- |
| IO epoch storage and layout | `src/server.c:649-789` |
| Foreign pin, IO registration, nested epochs, group-pin data and protocol | `src/server.c:977-1253` |
| Fake-client pin fields and snapshot lookup | `src/server.h:1885-1934`, `src/server.h:5881-5902` |
| Worker quiescence and owner-private reclaim fields | `src/server.h:2527-2677` |
| Retire node, batch, table layouts and constants | `src/flatstore.h:56-117` |
| Retire tags, payload dispatch, discard, enqueue, and node pool | `src/flatstore.c:25-68`, `src/flatstore.c:96-197` |
| Flat kvstore acquire/swap and retirement adapters | `src/kvstore.c:74-97` |
| Batch layout, close, readiness, drain, budgets, worker/main reclaim | `src/server.c:8931-9233` |
| Replaced-table retirement and resize publication | `src/server.c:9147-9178`, `src/server.c:9379-9447` |
| Worker pass announcements and reclaim call | `src/server.c:21781-21842`, `src/server.c:22361-22364` |
| Batch runtime-dimension initialization | `src/server.c:22816-22827` |
| Version/stamp/retire states and metadata accessors | `src/object.h:105-180`, `src/object.h:219-255` |
| Physical-retire helper, arm path, detached-bag path, callback | `src/db.c:922-942`, `src/db.c:1024-1131`, `src/db.c:1134-1405` |
| Owner-local publish and prune invocation | `src/server.c` (`csMsetOwnerApply`, `csMsetOwnerPublished`, `csOwnerPublishStep`) |
| Lifecycle reference and nonfatal owner audit | `src/server.c:344-425` |

## Mechanisms

- [Group-pin slots](mechanisms/buffers/group-pin-slots.md)
- [Freeback ring](mechanisms/buffers/freeback-ring.md)
- [QSBR grace](mechanisms/algorithms/qsbr-grace.md)
- [Reclaim budget](mechanisms/algorithms/reclaim-budget.md)
