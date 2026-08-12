# `pf_batches`, `pf_gated`, `pf_issued`, `prefetch_ex_xnode_issued`, and `prefetch_io_xnode_issued` — prefetch engagement counters

## What is counted

The live worker-storage mechanism records per-worker batch entries, gate returns, and issued prefetch stages in `exThread`; two additional cache-line-sharded atomic arrays record mode-2 cross-node EX-side carrier hints and IO-side reply hints. INFO folds each family into process-wide totals. (`src/server.h:2595-2601`, `src/server.c:154-188`, `src/server.c:19063-19074`, `src/server.c:19524-19548`)

There are no live identifiers spelled `prefetch_batches`, `prefetch_gated`, `prefetch_issued`, `ex_xnode_issued`, or `io_xnode_issued`. Those are brief shorthand: the exact storage fields are `pf_batches`, `pf_gated`, and `pf_issued`, while the exact cross-node arrays are `prefetch_ex_xnode_issued` and `prefetch_io_xnode_issued`. (`src/server.h:2595-2601`, `src/server.c:166-169`)

Two flat-storage proof counters, `pf_issued_slot` and `pf_issued_kvobj`, are exported with the main three and are part of the same observability surface. (`src/server.h:2713-2718`, `src/server.c:19066-19074`, `src/server.c:19524-19528`)

## Worker-local storage counters

| Exact identifier | Exact type | Increment and unit | INFO name |
|---|---|---|---|
| `exThread.pf_batches` | plain `unsigned long long` | `+1` on each enabled `exPrefetchBatch` entry, after the mode-0 return and before the L3 gate. (`src/server.h:2595-2601`, `src/server.c:21130-21156`) | `tomo_prefetch_batches` (`src/server.c:19524`) |
| `exThread.pf_gated` | plain `unsigned long long` | `+1` when the estimated key count is strictly less than `pf_cached_min` and the batch returns before the FSM. (`src/server.c:21199-21225`) | `tomo_prefetch_gated` (`src/server.c:19525`) |
| `exThread.pf_issued` | plain `unsigned long long` | Adds the Boolean `issued` once per scoreboard visit, so its unit is a visit/stage advance that issued at least one prefetch, not necessarily one machine prefetch instruction. `PFS_STRUCT`, for example, calls `redis_prefetch_read` twice but adds one. (`src/server.c:21288-21303`, `src/server.c:21417-21423`) | `tomo_prefetch_issued` (`src/server.c:19526`) |
| `exThread.pf_issued_slot` | plain `unsigned long long` | Counts FLAT home-slot hints; a batch-local `unsigned int` increments with each slot prefetch and is folded once at batch end if nonzero. (`src/server.c:21288`, `src/server.c:21337-21350`, `src/server.c:21425-21427`) | `tomo_prefetch_issued_slot` (`src/server.c:19527`) |
| `exThread.pf_issued_kvobj` | plain `unsigned long long` | Counts tag-matched FLAT kvobj hints; a batch-local `unsigned int` increments only when the live/tag test yields a non-null kvobj and is folded once at batch end if nonzero. (`src/server.c:21385-21399`, `src/server.c:21425-21427`) | `tomo_prefetch_issued_kvobj` (`src/server.c:19528`) |

The first three fields are adjacent in the owner-written part of `exThread`; the two FLAT proof counters are adjacent at the very end of the structure so adding them did not shift preceding fields. None has `_Atomic`, an alignment attribute, or padding of its own, so their declared payload is five `sizeof(unsigned long long)` values rather than five isolated cache lines. (`src/server.h:2585-2601`, `src/server.h:2702-2719`)

The worker selects its counter block with `server.exThreads[iotid - (TOMO_IO_THREADS_MAX + 1)]` and is the single writer. INFO directly reads and sums every configured worker slot; the source explicitly accepts those racy plain reads for statistics, so this family has no atomic memory ordering or synchronization guarantee for a snapshot. (`src/server.c:21154-21156`, `src/server.h:2595-2601`, `src/server.c:19063-19074`)

`initExThreads` zero-initializes all worker counter fields by allocating the `exThread` array with `zcalloc`. (`src/server.c:22816-22827`)

`resetServerStats` does not clear these five `exThread` fields: its prefetch clearing resets the xnode arrays and the separate upstream `stat_total_prefetch_*` fields, while the worker fields are not among those assignments. (`src/server.c:5375-5477`)

## `prefetch_ex_xnode_issued` and `prefetch_io_xnode_issued`

The exact element type is:

```c
typedef struct tomoPrefetchCounter {
    _Atomic unsigned long long value;
    char _pad[CACHE_LINE_SIZE - sizeof(_Atomic unsigned long long)];
} __attribute__((aligned(CACHE_LINE_SIZE))) tomoPrefetchCounter;
```

The code statically asserts that one `tomoPrefetchCounter` is exactly `CACHE_LINE_SIZE`, then declares one `prefetch_ex_xnode_issued[TOMO_STAT_SLOTS]` array and one `prefetch_io_xnode_issued[TOMO_STAT_SLOTS]` array. (`src/server.c:154-169`)

`TOMO_STAT_SLOTS` is `TOMO_IO_THREADS_MAX + 1 + TOMO_EX_THREADS_MAX`; both maxima are 128, so each array has 257 cache-line-isolated slots. (`src/server.h:1486-1487`, `src/server.h:1517-1520`)

Therefore each array occupies exactly `257 * CACHE_LINE_SIZE` bytes: 16,448 bytes when `CACHE_LINE_SIZE` is 64, or 32,896 bytes on Apple AArch64 where it is 128; both arrays together occupy 32,896 or 65,792 bytes, respectively. (`src/config.h:38-43`, `src/server.c:154-169`)

The slot mapping is `iotid`: slot 0 is main, IO identities occupy the low range, and worker `wid` uses `TOMO_IO_THREADS_MAX + 1 + wid`. Padding gives each producer identity its own cache line. (`src/server.h:1517-1520`, `src/server.c:23365-23366`)

Both xnode producers require their corresponding runtime level to be exactly 2. The integer configurations admit 0 through 2; `tomokv-prefetch-ex` defaults to 1 and `tomokv-prefetch-io` defaults to 0. (`src/config.c:3206-3217`, `src/server.c:22042-22050`, `src/server.c:4251-4253`)

### Atomic update and read protocol

`tomoPrefetchCounterBump(counter, issued)` does nothing for zero and otherwise updates `counter[iotid].value` through `tomoRelaxedBump`. That macro performs an atomic relaxed load followed by an atomic relaxed store of `old + issued`; it is deliberately not an atomic fetch-add. (`src/server.c:179-182`, `src/server.h:1613-1622`)

`tomoPrefetchCounterTotal` is the INFO-side consumer: it traverses all 257 slots and sums `atomic_load_explicit(..., memory_order_relaxed)`. These atomics provide defined untorn observations, but their relaxed ordering does not publish or consume any prefetch-related payload; they are statistics, not a handoff channel. (`src/server.c:184-188`, `src/server.h:1613-1622`)

`resetServerStats`, used both for startup initialization and `CONFIG RESETSTAT`, clears every xnode slot with a relaxed atomic store. A concurrent producer update may therefore be observed on either side of the reset boundary; the code supplies no stronger snapshot protocol. (`src/server.c:5375-5387`, `src/server.h:1621-1622`)

### EX-side counter

In mode 2, when the popped producer lane and worker are cross-node, the worker initializes `tomoMessagePrefetch`, runs `exPrefetchBatch`, then calls `tomoMessagePrefetchCarriers`. (`src/server.c:22042-22051`)

The carriers came through an IO-producer/worker-consumer SPSC queue: the IO side release-stores `tail` after writing `jobs[]`, and the worker refreshes `cached_tail` with an acquire load before copying the popped prefix. The counter update itself is only the later relaxed statistic and does not participate in that publication. (`src/server.c:20852-20888`, `src/server.c:21024-21053`, `src/server.c:179-182`)

`tomoMessagePrefetchCarriers` prefetches one future `client` carrier per remaining slot and adds the initial `remaining` count to `prefetch_ex_xnode_issued`. One counter unit is therefore one selected future message: that message caused one queue-cell hint in `tomoMessagePrefetchInit` and one carrier-header hint in `tomoMessagePrefetchCarriers`, but the counter is increased only once. (`src/server.c:21063-21088`)

INFO exports the relaxed sum as `tomokv_prefetch_ex_xnode_issued`. (`src/server.c:19544-19548`)

### IO-side counter

Mode-2 dispatch records cross-node provenance in the IO-owned `prefetch_io_xnode_slots` bitmap for both direct worker dispatch and cross-shard sub dispatch. (`src/server.c:3910-3917`, `src/server.c:12544-12550`, `src/server.h:1867-1869`)

On the live-connection splice path, after the IO drain observes slot completion, it first requires the current `cross_node_any[iotid]` acquire-load to be nonzero. Inside that branch, it clears a matching provenance bit even if mode 2 has since been disabled; only while the current `prefetch_io_level` is still 2 does it prefetch the completed reply buffers and add the helper's returned count to `prefetch_io_xnode_issued`. The disconnected/`CLIENT_CLOSE_ASAP` teardown path bypasses this counter and the entire topology/provenance block. (`src/server.c:4134-4214`, `src/server.c:4236-4254`)

The worker is the sole completion publisher and release-stores the ready byte after its reply writes; the owning IO thread acquire-loads that byte before walking the buffers. The provenance bitmap is IO-owned, and the xnode counter's relaxed update occurs only after this payload handoff. (`src/server.c:3149-3168`, `src/server.c:22248-22252`, `src/server.c:4236-4253`, `src/server.h:1867-1869`)

That returned count is the number of explicit hints issued by the reply walker: one per covered buffer cache line, plus hints for list blocks and applicable cross-shard carrier structures. (`src/server.c:4051-4064`, `src/server.c:4067-4117`)

These are software counts of calls to `redis_prefetch_read`; when compiler prefetch support is unavailable that macro is a no-op expression, but the surrounding count still advances. (`src/config.h:120-136`, `src/server.c:4057-4064`, `src/server.c:4079-4085`)

INFO exports the relaxed sum as `tomokv_prefetch_io_xnode_issued`. (`src/server.c:19544-19548`)

The EX and IO xnode values therefore have different units—selected future messages versus individual reply-walker hint calls—and should not be compared as symmetric event counts. (`src/server.c:21063-21088`, `src/server.c:4051-4117`, `src/server.c:4251-4253`)

## INFO folding and interpretation

Before emitting INFO, the server sums the five plain worker fields across `[0, server.num_workers)` and prints the results in the `# Stats` section. (`src/server.c:19063-19074`, `src/server.c:19202-19207`, `src/server.c:19524-19528`)

The source makes disabled and gated operation distinguishable: mode 0 leaves `pf_batches` unchanged, whereas an enabled call increments `pf_batches` before it can increment `pf_gated`. The code comment identifies `tomo_prefetch_gated == tomo_prefetch_batches` as the signal that every counted batch was stopped by the gate. (`src/server.c:21121-21133`, `src/server.c:21154-21156`, `src/server.c:19063-19065`)

`tomo_prefetch_issued / tomo_prefetch_batches` is stage-issue density, not instructions per batch, because `pf_issued` folds the Boolean `issued` once per scoreboard visit. (`src/server.c:21288-21303`, `src/server.c:21417-21423`)

See [the L3 footprint gate](l3-footprint-gate.md), [the prefetch state machine](prefetch-stages.md), [message-carrier prefetch](message-carrier-prefetch.md), and [cross-node prefetch](crossnode-prefetch.md) for the producers behind these totals.

## Separate retained upstream counters

`redisServer` also contains plain `long long stat_total_prefetch_batches` and `stat_total_prefetch_entries`, exported as `io_threaded_total_prefetch_batches` and `io_threaded_total_prefetch_entries`; they are not aliases of the Tomo worker counters above. (`src/server.h:3671-3672`, `src/server.c:19529-19534`)

These two plain fields are adjacent in `redisServer` and have no dedicated atomic, padding, alignment, or cache-line wrapper; their declared payload is two `sizeof(long long)` values within the server structure. (`src/server.h:3671-3672`)

Their producers live in `memory_prefetch.c`: `stat_total_prefetch_entries` increments when an upstream `KeyPrefetchInfo` reaches `PREFETCH_DONE`, and `stat_total_prefetch_batches` increments only when `prefetchCommands` has more than one key before calling `dictPrefetch`. (`src/memory_prefetch.c:135-145`, `src/memory_prefetch.c:340-375`)

The file itself labels this upstream batch dead, the Tomo initialization call was removed, and a supported Tomo configuration refuses `io-threads > 1`; the upstream consumer loop iterates only thread IDs `1 .. io_threads_num-1`, so that producer path has no IO-thread instance in a successful Tomo boot. (`src/memory_prefetch.c:85-90`, `src/server.c:6260-6262`, `src/server.c:5700-5715`, `src/iothread.c:694-699`)

Unlike the worker-local `pf_*` fields, both retained upstream fields are explicitly set to zero by `resetServerStats`. (`src/server.c:5471-5473`)
