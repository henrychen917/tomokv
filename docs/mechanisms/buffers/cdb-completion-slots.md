# `cdbSlots` — EX-to-IO reply-completion cache line

## What it is

`cdbSlots` is the status-only completion channel for one real client's fake-client ring: it contains one atomic ready byte for every compile-time fake-ring slot and no reply payload. A completing execution context publishes a byte, and the real client's owning IO thread polls that byte before consuming the fake's reply. [`src/server.h:1624-1649`](../../../src/server.h#L1624-L1649) [`src/server.c:4236-4241`](../../../src/server.c#L4236-L4241)

The real client owns a heap array through `clientTail(c)->reply_cdb`. Full/tail-bearing fakes set their own tail pointer to `NULL`, while a 320-byte core fake has no `clientExecTail` and therefore no `reply_cdb` member until promotion; every completion nevertheless addresses the real parent's array. [`src/server.h:1778-1786`](../../../src/server.h#L1778-L1786) [`src/networking.c:172-185`](../../../src/networking.c#L172-L185) [`src/networking.c:357-442`](../../../src/networking.c#L357-L442) [`src/networking.c:629-644`](../../../src/networking.c#L629-L644)

For an ordinary worker-dispatched fake, the channel is SPSC at the individual `(cdb, slot)` byte: that fake generation has one `0 -> 1` publisher and its owning IO thread is the one `1 -> 0` clearer. [`src/server.c:3149-3157`](../../../src/server.c#L3149-L3157)

## Exact representation and footprint

```c
typedef struct cdbSlots {
    redisAtomic uint8_t ready[TOMO_PIPELINE_DEPTH_MAX];
    char _pad[CACHE_LINE_SIZE -
              sizeof(redisAtomic uint8_t) * TOMO_PIPELINE_DEPTH_MAX];
} __attribute__((aligned(CACHE_LINE_SIZE))) cdbSlots;
```

The declaration fixes `TOMO_PIPELINE_DEPTH_MAX` at 32, asserts that each `redisAtomic uint8_t` occupies one byte and is always lock-free, aligns the struct to `CACHE_LINE_SIZE`, and asserts that `sizeof(cdbSlots) == CACHE_LINE_SIZE`. [`src/server.h:1558-1559`](../../../src/server.h#L1558-L1559) [`src/server.h:1638-1649`](../../../src/server.h#L1638-L1649)

Under the C11 atomic branch used by the explicit atomic operations, `redisAtomic` expands to `_Atomic`, making each status element an `_Atomic uint8_t`. [`src/atomicvar.h:90-98`](../../../src/atomicvar.h#L90-L98) [`src/server.c:3158-3168`](../../../src/server.c#L3158-L3168)

The exact in-line layout is therefore 32 bytes of `ready[0..31]` followed by `CACHE_LINE_SIZE - 32` bytes of `_pad`: 32 bytes of padding on the normal 64-byte-line definition, or 96 bytes on Apple/AArch64's 128-byte-line definition. `config.h` selects 128 only for Apple/AArch64 and 64 otherwise, unless `CACHE_LINE_SIZE` was already supplied. [`src/config.h:38-44`](../../../src/config.h#L38-L44) [`src/server.h:1639-1649`](../../../src/server.h#L1639-L1649)

Every bus reserves all 32 status bytes even when a client's current runtime ring is smaller; dispatch masks into the current `ring_size`, while creation initializes the entire compile-time status array. [`src/networking.c:640-643`](../../../src/networking.c#L640-L643) [`src/server.c:8304-8314`](../../../src/server.c#L8304-L8314) [`src/server.c:8423-8434`](../../../src/server.c#L8423-L8434)

One CDB is exactly one cache line, and the aligned array makes successive CDBs start on successive lines; workers mapped to different CDB indices therefore do not write the same completion line. Workers mapped to the same CDB can write different ready bytes in that one line. [`src/server.h:1626-1649`](../../../src/server.h#L1626-L1649)

For `ncdb` buses, the usable array footprint is exactly `ncdb * CACHE_LINE_SIZE` bytes. `createClient` requests `ncdb * sizeof(cdbSlots) + CACHE_LINE_SIZE + sizeof(void *)` bytes, rounds `raw + sizeof(void *)` upward with `(x + CACHE_LINE_SIZE - 1) & ~(CACHE_LINE_SIZE - 1)`, and stores `raw` in the pointer-sized word immediately before the aligned array. [`src/networking.c:629-639`](../../../src/networking.c#L629-L639)

The `reply_cdb` pointer is the first member of `clientExecTail`, which places it at full-client offset 320 and lets publication reach the array without another dependent field lookup. [`src/server.h:1775-1784`](../../../src/server.h#L1775-L1784) [`src/server.h:1953-1957`](../../../src/server.h#L1953-L1957)

## Bus count and routing formulas

At startup, the live bus count is computed as `req = detectL3Domains() > 1 ? server.num_workers : 1`, then clamped to at most `server.num_workers`, at most `NUM_CDB_MAX` (256), and at least one; the result is stored in `server.num_cdb`. [`src/server.c:6094-6106`](../../../src/server.c#L6094-L6106) [`src/server.h:1638-1639`](../../../src/server.h#L1638-L1639)

`cdbIndexFor(ex_id)` uses these exact branches: return 0 when `server.num_cdb == 1`; return `ex_id` when `ex_id < server.num_cdb`; otherwise return `ex_id % server.num_cdb`. [`src/server.c:3139-3147`](../../../src/server.c#L3139-L3147)

An ordinary worker route captures that result in `fake->cdb` before queueing the fake: the express branch maps `ex_id`, the indivisible T6 branch maps `t6_worker`, and the general-worker branch maps `ex_id`; the synchronous inline branch instead sets `fake->cdb = 0`. [`src/server.c:8500-8517`](../../../src/server.c#L8500-L8517) [`src/server.c:8591-8607`](../../../src/server.c#L8591-L8607)

Cross-shard group constructors route the group head's completion through CDB 0; examples include pipeline groups, general gather groups, and two-hop groups. [`src/server.c:12938-12953`](../../../src/server.c#L12938-L12953) [`src/server.c:13629-13635`](../../../src/server.c#L13629-L13635) [`src/server.c:14405-14411`](../../../src/server.c#L14405-L14411)

## Initialization and lifetime

`createClient` chooses `ncdb = server.num_cdb > 0 ? server.num_cdb : 1`, allocates and aligns that many buses, then initializes every `ready[cc][slot]` for `cc < ncdb` and `slot < TOMO_PIPELINE_DEPTH_MAX` to zero with relaxed stores. [`src/networking.c:629-644`](../../../src/networking.c#L629-L644)

A real client with in-flight fakes is deferred instead of freed; after the fake ring drains, `freeClient` frees the saved raw CDB allocation and nulls `reply_cdb`. This prevents a worker publication from targeting reclaimed client memory. [`src/networking.c:2710-2718`](../../../src/networking.c#L2710-L2718) [`src/networking.c:2725-2738`](../../../src/networking.c#L2725-L2738)

## Protocol, exactly as coded

1. The IO-side dispatch path computes `fslot = dispatchid & ring_mask`, obtains or creates `fakeClients[fslot]`, and stamps `fake->fake_slot = fslot`; it refuses a dispatch when `dispatchid - flushid == ring_size`. [`src/server.c:8314-8325`](../../../src/server.c#L8314-L8325) [`src/server.c:8423-8434`](../../../src/server.c#L8423-L8434)

2. For an express or general worker route, dispatch captures `fake->cdb = cdbIndexFor(ex_id)` before publishing the fake to that worker's queue; the T6 branch applies the same formula to `t6_worker`. [`src/server.c:8500-8517`](../../../src/server.c#L8500-L8517) [`src/server.c:8591-8604`](../../../src/server.c#L8591-L8604)

3. Each worker captures its immutable bus as `ctx->wcdb = cdbIndexFor(worker->id)`. After executing an ordinary batch, it saves each fake's parent and slot, then calls `cdbSlotPublish(parent, ctx->wcdb, slot)` for every completion; the loop is the worker's final access through each saved parent. [`src/server.c:21680-21685`](../../../src/server.c#L21680-L21685) [`src/server.c:21720-21729`](../../../src/server.c#L21720-L21729) [`src/server.c:22242-22252`](../../../src/server.c#L22242-L22252)

4. `cdbSlotPublish` release-stores byte value 1. The synchronous inline branch uses the same helper after `call(fake, flags)`, so its reply writes obey the same publication edge even though producer and consumer are the IO execution path rather than separate EX and IO threads. [`src/server.c:3162-3165`](../../../src/server.c#L3162-L3165) [`src/server.c:8624-8640`](../../../src/server.c#L8624-L8640)

5. A last cross-shard sub is selected by either `g->nsub == 1` or `atomic_fetch_sub_explicit(&g->pending, 1, memory_order_acq_rel) == 1`; non-versioned and stage-only versioned completions publish the group head's captured `(cdb, fake_slot)`. Final versioned-write completion instead reaches `csMsetInstallDone`, which puts the group through `INSTALL_READY` and owner STAMP/CANCEL work. The last successful stamp publishes the shared `commit_ts` and encoded global clock, after which `FINAL_READY` queues PRUNE and publishes the head CDB; cancellation likewise waits for every CANCEL before terminal CDB publication. [`src/server.c`](../../../src/server.c)

6. `handleWorkerReplies` examines fakes in connection order while `flushid != dispatchid`, derives `slot = flushid & ring_mask`, and acquire-loads `reply_cdb[fake->cdb].ready[slot]`; a zero makes it stop at that first incomplete slot. [`src/server.c:4236-4241`](../../../src/server.c#L4236-L4241)

7. After consuming or discarding the completed fake, the IO path relaxed-stores zero through `cdbSlotClear`, retires the fake state, and increments `flushid`; the close-as-soon-as-possible drain follows the same ready-test, clear, and increment sequence. [`src/server.c:3166-3169`](../../../src/server.c#L3166-L3169) [`src/server.c:4148-4155`](../../../src/server.c#L4148-L4155) [`src/server.c:4200-4207`](../../../src/server.c#L4200-L4207) [`src/server.c:4320-4341`](../../../src/server.c#L4320-L4341)

8. When a cross-shard head keeps the same fake-ring slot across another stage, the IO drain clears the old ready byte before pushing the new stage. `csHopCommit` makes the coded order `pending -> phase -> clear -> push`, and `csLaunchHop2` likewise clears before rebuilding and publishing an HOP2 scatter. [`src/server.c:14550-14562`](../../../src/server.c#L14550-L14562) [`src/server.c:14800-14808`](../../../src/server.c#L14800-L14808)

## Atomic ordering and ownership

| Operation | Thread/role | Exact operation | Meaning |
| --- | --- | --- | --- |
| Initialize | real-client creator | relaxed store of 0 | No generation is complete yet. [`src/networking.c:635-643`](../../../src/networking.c#L635-L643) |
| Publish | completing worker, final group completer, or inline IO execution | release store of 1 | Publishes reply payload and fake lifetime state. [`src/server.c:3149-3165`](../../../src/server.c#L3149-L3165) |
| Poll | owning IO drain | acquire load and test `!= 0` | Pairs with the release publication before reply consumption. [`src/server.c:3158-3161`](../../../src/server.c#L3158-L3161) [`src/server.c:4236-4241`](../../../src/server.c#L4236-L4241) |
| Clear | owning IO drain/stage driver | relaxed store of 0 | Publishes no payload; it marks the byte reusable. [`src/server.c:3154-3168`](../../../src/server.c#L3154-L3168) |

The byte remains atomic even though each generation has one publisher and one clearer, so every poll must reload it; the source also requires atomic characters to be always lock-free. [`src/server.c:3149-3157`](../../../src/server.c#L3149-L3157) [`src/server.h:1644-1647`](../../../src/server.h#L1644-L1647)

## Enforced invariants

- A ready byte has only the protocol values 0 and 1: allocation and clearing store 0, while completion stores 1. [`src/networking.c:640-643`](../../../src/networking.c#L640-L643) [`src/server.c:3162-3168`](../../../src/server.c#L3162-L3168)
- A slot is not retired or reused until its IO owner has observed readiness and cleared the byte; the drain increments `flushid` only after the clear, and dispatch refuses to overrun `ring_size`. [`src/server.c:8314-8325`](../../../src/server.c#L8314-L8325) [`src/server.c:4334-4341`](../../../src/server.c#L4334-L4341)
- For an ordinary worker-dispatched fake, publication and draining agree on the CDB because dispatch captures `fake->cdb` once while the worker's `wcdb` is derived from the same immutable mapping. Cross-shard heads instead capture CDB 0: non-versioned and stage-only last subs publish the stored head CDB directly, while a final versioned completion path may publish it from whichever completion worker acquires the connection's drain latch. [`src/server.c:3139-3147`](../../../src/server.c#L3139-L3147) [`src/server.c:8591-8604`](../../../src/server.c#L8591-L8604) [`src/server.c:12938-12953`](../../../src/server.c#L12938-L12953) [`src/server.c:21680-21685`](../../../src/server.c#L21680-L21685) [`src/server.c:10336-10395`](../../../src/server.c#L10336-L10395) [`src/server.c:22171-22199`](../../../src/server.c#L22171-L22199)
- Reply order is connection order, not worker completion order: the drain stops at the first not-ready `flushid` slot even if later bytes are already 1. [`src/server.c:4221-4241`](../../../src/server.c#L4221-L4241)
- Re-arming a multi-stage group clears the stale 1 before any new sub can publish the next 1, preventing the new completion from being overwritten by a late clear. [`src/server.c:14550-14562`](../../../src/server.c#L14550-L14562)
- Every CDB occupies one complete aligned cache line, so no adjacent CDB shares a line. [`src/server.h:1638-1649`](../../../src/server.h#L1638-L1649)

## Direct users

- `createClient` allocates, aligns, and initializes the array; `freeClient` releases the saved raw allocation after in-flight work is gone. [`src/networking.c:629-644`](../../../src/networking.c#L629-L644) [`src/networking.c:2715-2738`](../../../src/networking.c#L2715-L2738)
- `processCommand` stamps the fake's CDB route and publishes synchronous inline completions. [`src/server.c:8500-8506`](../../../src/server.c#L8500-L8506) [`src/server.c:8591-8640`](../../../src/server.c#L8591-L8640)
- `exSlice` publishes ordinary worker completions and the last-sub completion for cross-shard groups. [`src/server.c:22171-22199`](../../../src/server.c#L22171-L22199) [`src/server.c:22242-22252`](../../../src/server.c#L22242-L22252)
- `handleWorkerReplies` is the normal acquire-polling consumer and relaxed clearer. [`src/server.c:4120-4129`](../../../src/server.c#L4120-L4129) [`src/server.c:4236-4241`](../../../src/server.c#L4236-L4241) [`src/server.c:4334-4341`](../../../src/server.c#L4334-L4341)
- `csMsetInstallDone` publishes final ordered atomic-write completion. [`src/server.c:10336-10412`](../../../src/server.c#L10336-L10412)
- `csAtomicAbortIncomplete`, `csMsetnxAdvanceReservations`, `csAtomicNxAdvance`, `csPipeAdvance`, `csSortStartDeref`, `csHopCommit`, and `csLaunchHop2` test, clear, or re-arm the same head byte for multi-stage cross-shard protocols. [`src/server.c:10415-10426`](../../../src/server.c#L10415-L10426) [`src/server.c:12716-12744`](../../../src/server.c#L12716-L12744) [`src/server.c:12828-12880`](../../../src/server.c#L12828-L12880) [`src/server.c:13374-13464`](../../../src/server.c#L13374-L13464) [`src/server.c:14210-14239`](../../../src/server.c#L14210-L14239) [`src/server.c:14550-14571`](../../../src/server.c#L14550-L14571) [`src/server.c:14800-14808`](../../../src/server.c#L14800-L14808)

The slot index and generation lifetime belong to the related [fake-client ring](fake-client-ring.md); `cdbSlots` is only that ring's completion-publication plane. [`src/server.c:8423-8434`](../../../src/server.c#L8423-L8434) [`src/server.h:1624-1649`](../../../src/server.h#L1624-L1649)
