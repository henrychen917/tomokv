# `tomoWkrLock` / `tomoWkrTrylock` / `tomoWkrUnlock` / `tomoWkrLockPub` / `tomoWkrUnlockPub` — per-worker owner exclusion lock

## Identifier and mechanism

The mechanism is a table of one-byte CAS spinlocks indexed by worker ID. `tomoWkrTrylock` performs the acquisition CAS, `tomoWkrLock` spins until that CAS succeeds, and `tomoWkrUnlock` release-stores the unlocked value. `tomoWkrLockPub` and `tomoWkrUnlockPub` are exported one-line wrappers used from other translation units. ([src/server.c:9659-9684](../../../src/server.c#L9659-L9684), [src/server.h:6506-6510](../../../src/server.h#L6506-L6510))

There is no identifier named `tomoWkrPub` in the pinned source. The brief's “Pub” name corresponds to the two actual wrapper identifiers `tomoWkrLockPub` and `tomoWkrUnlockPub`; the internal try/lock/unlock functions remain `static inline`. ([src/server.c:9668-9684](../../../src/server.c#L9668-L9684), [src/server.h:6506-6510](../../../src/server.h#L6506-L6510))

This is the S2 owner-exclusion lock: the ordinary single-key worker path locks the worker currently named by `ex_bucket_table[b]` across the command procedure, while operations that touch node-shared state take a fixed-order set of these worker locks. ([src/server.c:21519-21525](../../../src/server.c#L21519-L21525), [src/server.c:21555-21601](../../../src/server.c#L21555-L21601))

## Exact representation, byte size, and cache lines

The complete lock table is declared as:

```c
static struct { _Atomic uint8_t v; uint8_t pad[63]; }
    __attribute__((aligned(64))) tomo_wkr_lock[TOMO_EX_THREADS_MAX + 1];
```

The state byte `v` is the only semantic field: `0` is unlocked and successful acquisition changes it to `1`; `pad[63]` supplies no state. The record type and array base are given 64-byte alignment by the GCC attribute. ([src/server.c:9659-9671](../../../src/server.c#L9659-L9671), [src/server.c:9679-9680](../../../src/server.c#L9679-L9680))

`TOMO_EX_THREADS_MAX` is 128, so the table contains 129 records. With the source's one-byte atomic state and 63-byte pad, one record is 64 bytes and the table payload is `129 * 64 = 8,256` bytes. The declaration has no separate `sizeof` static assertion; the nearby CDB assertions establish that the C11 byte-atomic configuration used by this tree occupies one byte. ([src/server.h:1470-1487](../../../src/server.h#L1470-L1487), [src/server.h:1643-1649](../../../src/server.h#L1643-L1649), [src/atomicvar.h:90-98](../../../src/atomicvar.h#L90-L98), [src/server.c:9663-9664](../../../src/server.c#L9663-L9664))

The lock table hard-codes `64`, rather than using `CACHE_LINE_SIZE`. On the default non-Apple-AArch64 branch, where `CACHE_LINE_SIZE` is 64, every record has a separate cache line; on Apple AArch64 the configured cache-line constant is 128, so the literal declaration permits two adjacent 64-byte lock records in one configured line. ([src/config.h:38-44](../../../src/config.h#L38-L44), [src/server.c:9659-9664](../../../src/server.c#L9659-L9664)) There is no further pad between array elements and no owner metadata, waiter count, ticket, or recursion field. ([src/server.c:9663-9664](../../../src/server.c#L9663-L9664))

## Lock and unlock algorithm

### `tomoWkrTrylock(w)`

1. Initialize a local `uint8_t expected = 0`. ([src/server.c:9668-9669](../../../src/server.c#L9668-L9669))
2. Execute `atomic_compare_exchange_strong_explicit(&tomo_wkr_lock[w].v, &expected, 1, memory_order_acquire, memory_order_relaxed)`. ([src/server.c:9669-9671](../../../src/server.c#L9669-L9671))
3. Return the CAS result: success changes `v` from `0` to `1` with acquire ordering; failure leaves the lock held and uses relaxed ordering. ([src/server.c:9668-9672](../../../src/server.c#L9668-L9672))

The helper does not check `w`, expose the observed byte, or distinguish contention from an invalid/reentrant call. ([src/server.c:9668-9672](../../../src/server.c#L9668-L9672))

### `tomoWkrLock(w)`

The lock first calls `tomoWkrTrylock(w)` and returns on success. On failure it calls `tmIoWaitBegin()`, repeatedly executes `exPauseCpu()` and retries the strong CAS until it succeeds, then calls `tmIoWaitEnd()`. There is no queue, ticket, fairness rule, sleep, or yield branch in this loop. ([src/server.c:9673-9677](../../../src/server.c#L9673-L9677))

### `tomoWkrUnlock(w)` and public wrappers

Unlock performs `atomic_store_explicit(&tomo_wkr_lock[w].v, 0, memory_order_release)`. The public functions simply call the corresponding internal lock or unlock and add no branch or ordering operation. ([src/server.c:9679-9684](../../../src/server.c#L9679-L9684))

The successful acquire CAS pairs with a preceding release unlock of the same worker byte, so data-structure work inside one holder's critical section precedes a later holder's work. Failed probes are relaxed because they convey no ownership. ([src/server.c:9668-9681](../../../src/server.c#L9668-L9681))

## Owner-side callers

The following direct callers are owner-side execution or maintenance paths. All rows except the ordinary S2 branch derive the record from the executing worker identity; that branch deliberately reloads the bucket table and relies on the migration fence to keep the fresh mapping equal to the executing owner. ([src/server.c:21588-21601](../../../src/server.c#L21588-L21601), [src/server.c:15966-15972](../../../src/server.c#L15966-L15972))

| Caller | Exact critical section |
| --- | --- |
| [`csStampDrain`](owner-op-stamp-lane.md) | Locks `worker->id` around each popped batch of owner-affine stamp/prune/cancel operations, then unlocks before lifecycle-reference release and `stamp_pending` decrement. ([src/server.c:9987-10050](../../../src/server.c#L9987-L10050)) |
| T6/full-call worker branch in `exSlice` | Sets `w = fake->tomo_local_worker`, asserts the current EX identity equals `w`, locks, executes the full transaction/script `call`, then unlocks. ([src/server.c:21526-21554](../../../src/server.c#L21526-L21554)) |
| Ordinary S2 branch in `exSlice` | Only when the command declares its first key at position 1 and has `argv[1]`, derives or reuses bucket `b`, reloads `mlk_wkr = ex_bucket_table[b]`, locks across `fake->cmd->proc(fake)`, and conditionally unlocks. ([src/server.c:21574-21601](../../../src/server.c#L21574-L21601)) |
| Flush sentinel in `exSlice` | Locks `worker->id` while touching watched keys for the selected DB range. ([src/server.c:22108-22118](../../../src/server.c#L22108-L22118)) |
| Cross-shard subcommand in `exSlice` | Locks `worker->id` around `csSubExec(fake)`. ([src/server.c:22155-22170](../../../src/server.c#L22155-L22170)) |
| `dbFlatInsertWait` | Drops `worker->id` before leaving the flat section and waiting for resize, reacquires it before republishing the section, and drops it again if resize is still active. ([src/db.c:504-526](../../../src/db.c#L504-L526)) |
| `tomoVersionPruneAfterGrace` / `tomoVersionPruneFinish` | Derives `owner` from the executing worker identity, locks before walking or updating the version bag, and unlocks in the common finish helper. ([src/db.c:1134-1167](../../../src/db.c#L1134-L1167)) |
| `dbRandomKey` shared-node paths | Derives `wid` from the executing worker and locks it only around `expireIfNeeded` for both flat and dict-backed selection. ([src/db.c:1692-1713](../../../src/db.c#L1692-L1713), [src/db.c:1736-1749](../../../src/db.c#L1736-L1749)) |
| `exActiveExpireCycle` | Locks the current `wid` across its bounded whole-key expiry pass and unlocks at the pass exit. ([src/expire.c:234-258](../../../src/expire.c#L234-L258), [src/expire.c:288-307](../../../src/expire.c#L288-L307), [src/expire.c:359-365](../../../src/expire.c#L359-L365)) |

The ordinary S2 code chooses the lock from a fresh `ex_bucket_table[b]` read rather than asserting that it equals the current worker ID. The surrounding migration fence is responsible for preventing an old-owner command from crossing a cutover; the lock helper itself merely indexes the value supplied by its caller. ([src/server.c:21588-21601](../../../src/server.c#L21588-L21601), [src/server.c:15966-15972](../../../src/server.c#L15966-L15972))

## Who takes a worker lock off-owner

The literal call sites that can acquire a record belonging to another worker are:

- The hash-field-TTL command branch computes its node range as `wlo = node * wpn`, `whi = min(wlo + wpn, num_workers)`, locks every `lw` from `wlo` upward, executes the HFE procedure, and unlocks from `whi - 1` downward. A worker therefore holds its siblings' records as well as its own. ([src/server.c:21555-21573](../../../src/server.c#L21555-L21573))
- `exActiveSubexpiresCycle` computes the same node-wide interval, locks every record in ascending order, operates on the node-shared hash-field expiry store, and unlocks in descending order. ([src/expire.c:488-507](../../../src/expire.c#L488-L507), [src/expire.c:606-612](../../../src/expire.c#L606-L612))
- `unwatchAllKeys` reads the worker recorded on the first watched key and calls the public lock wrapper only when sharding is active and `tomoCurrentWorker() != worker`; it unlocks only when that conditional acquisition occurred. ([src/multi.c:473-490](../../../src/multi.c#L473-L490))

The ascending-acquire/reverse-release discipline is explicit at both node-wide call sites. Single-record users do not participate in a multi-lock cycle, and the node-wide users take the same total order. ([src/server.c:21555-21573](../../../src/server.c#L21555-L21573), [src/expire.c:488-507](../../../src/expire.c#L488-L507), [src/expire.c:606-612](../../../src/expire.c#L606-L612))

## Enforced invariants and limits

- At most one successful CAS holder exists for a given `w`: only `0 -> 1` succeeds, and the next acquisition cannot succeed until a release-store restores `0`. ([src/server.c:9668-9681](../../../src/server.c#L9668-L9681))
- Lock records are per worker, not per bucket; all ordinary keys whose fresh bucket mapping selects one worker serialize on that worker's byte. ([src/server.c:9641-9653](../../../src/server.c#L9641-L9653), [src/server.c:21588-21601](../../../src/server.c#L21588-L21601))
- The API is non-recursive. The active-expiry code explicitly keeps the node-wide subexpiry pass outside its own-lock region because reacquiring the included record would self-deadlock. ([src/expire.c:277-302](../../../src/expire.c#L277-L302))
- The helpers contain no bounds check and no owner check; callers must supply a valid worker index and obey the acquisition discipline. ([src/server.c:9668-9684](../../../src/server.c#L9668-L9684))
- The lock is unconditional in the execution paths shown above; the code contains no runtime enable/disable branch around the lock operations. ([src/server.c:21519-21525](../../../src/server.c#L21519-L21525), [src/server.c:21555-21601](../../../src/server.c#L21555-L21601), [src/server.c:22155-22170](../../../src/server.c#L22155-L22170))
