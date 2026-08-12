# `flatGroupPinSlot`: generation-counted dispatch-lifetime pin slot

## What it is

`flatGroupPinSlot` is the per-IO-identity QSBR structure that keeps FLAT values
reachable for the whole lifetime of an eligible cross-shard dispatch. Instead
of holding an inline `flat_epoch` region across asynchronous worker execution,
each dispatch records the current retire-batch close generation in a 4,096-cell
counter ring; reclamation defers any batch whose close generation is not older
than the slot's oldest live pin. (src/server.c:985-1015,
src/server.c:1175-1253, src/server.c:8936-8982,
src/server.c:9031-9035)

One `flatGroupPinSlot` represents an IO identity, not a fake-ring position or a
worker. `flat_group_pins` has `TOMO_IO_THREADS_MAX + 1` entries, while live access
is restricted to indices zero through
`flatIoHi() = min(server.io_threads + server.tm_ngrow_io,
TOMO_IO_THREADS_MAX)`. (src/server.h:1486-1487,
src/server.c:1000-1003, src/server.c:1082-1089,
src/server.c:1178-1181)

The fake carrier stores the selected close generation in
`tomo_read_snapshot_gen`, the MVCC frontier in `tomo_read_snapshot`, and a plain
`tomo_read_snapshot_pinned` lifetime flag, but it stores no IO-slot identifier.
Exit indexes by the current thread-local `flat_slot_owned`, so terminal drain must
run under the same IO identity that entered the pin. The relationship to the carrier ring
is documented in [the fake-client ring](fake-client-ring.md), and the versions
read under that snapshot are documented in
[the per-key version bag](version-bag.md). (src/server.h:1909-1924,
src/server.c:1178-1206, src/server.c:8465-8471,
src/server.c:4120-4341)

## Exact structures

The generation width is exactly 4,096 and its mask is 4,095. A static assertion
requires the width to be a power of two. (src/server.c:985-992)

Each cache-line-aligned `flatGroupPinSlot` contains the following fields in this
exact order. (src/server.c:993-1002)

| Field | Exact type and layout | Role |
| --- | --- | --- |
| `active` | `_Atomic uint64_t`, followed by `CACHE_LINE_SIZE - sizeof(_Atomic uint64_t)` bytes of `_pad_active` | Number of live group pins owned by this IO identity; it occupies the slot's first cache line by itself. (src/server.c:993-996, src/server.c:1186-1194, src/server.c:1211-1215) |
| `floor` | `_Atomic uint64_t`, at the beginning of the second cache line | Reclaimer-maintained oldest generation that may still have an outstanding pin. Entry initializes it on `active`'s zero-to-one transition, and a scanner that observes inactivity stores the current generation; exit itself does not update it, so its stored value may be stale while the mask bit is clear. (src/server.c:996-999, src/server.c:1192-1195, src/server.c:1211-1215, src/server.c:1232-1245) |
| `scan_lock` | `_Atomic int`, immediately after `floor`, followed by padding that completes the second cache line | Serializes pin registration with the reclaimer's floor scan. Entry spins with weak acquire CAS; a reclaimer uses one strong acquire CAS and defers if it fails. (src/server.c:996-999, src/server.c:1182-1185, src/server.c:1227-1231) |
| `pin_out` | `_Atomic uint64_t[4096]` | Per-generation outstanding-pin counts, indexed by `generation & 4095`. (src/server.c:989-1000, src/server.c:1192-1196, src/server.c:1206-1209) |

The type itself is aligned to `CACHE_LINE_SIZE`, and a static assertion requires
its total size to be a cache-line multiple; consequently adjacent entries of
`flat_group_pins[]` do not share a line. The explicit first- and second-line
padding also separates IO-hot `active` from reclaimer-written `floor` and
`scan_lock`. (src/server.c:985-1003)

`flatGroupPinMask` is a separate cache-line-aligned object containing
`_Atomic uint64_t bits[TOMO_IO_MASK_WORDS]` plus padding to exactly one cache
line. With `TOMO_IO_THREADS_MAX == 128`, `TOMO_IO_MASK_WORDS` expands to three,
and a static assertion requires `sizeof(flatGroupPinMask) == CACHE_LINE_SIZE`.
(src/server.h:1486-1487, src/server.h:2317-2320,
src/server.c:1004-1010)

Both `flat_group_pins` and `flat_group_pin_mask` have static storage duration and
no allocation or explicit initialization routine; C static initialization makes
all counters, locks, floors, cells, and mask bits start at zero. (src/server.c:993-1010)

`flat_batches_closed_n` is both the count of closed retire batches and the
monotone close-generation source; `flat_batches_freed_n` and
`flat_pin_wrap_blocks` are separate atomic progress counters. (src/server.c:1012-1015,
src/server.c:8977-8982, src/server.c:19206-19216)

## Byte footprint and cache-line story

The source fixes the first two regions of every slot at exactly two cache lines,
then appends 4,096 atomic 64-bit counters. Assuming an ABI on which
`sizeof(_Atomic uint64_t) == 8`, the counter ring is exactly 32,768 bytes and the
slot size is `2 * CACHE_LINE_SIZE + 32,768`; these byte totals are ABI-derived
rather than protected by an exact-size assertion. (src/server.c:989-1002)

| Configured cache line | ABI-derived `sizeof(flatGroupPinSlot)` | Cache-line allocation |
| --- | --- | --- |
| 64 bytes | 32,896 bytes | 1 line for `active`, 1 for `floor`/`scan_lock`, and 512 lines for `pin_out`: 514 lines total. (src/config.h:38-43, src/server.c:993-1002) |
| 128 bytes | 33,024 bytes | 1 line for `active`, 1 for `floor`/`scan_lock`, and 256 lines for `pin_out`: 258 lines total. (src/config.h:38-43, src/server.c:993-1002) |

On the same ABI, all 129 statically allocated slots occupy an ABI-derived
4,243,584 bytes with 64-byte lines or 4,260,096 bytes with 128-byte lines; only
the prefix through `flatIoHi()` participates in entry and scan loops. The
separate engaged-slot mask occupies exactly one configured cache line.
(src/server.h:1486-1487, src/server.c:1000-1010,
src/server.c:1082-1089, src/server.c:1220-1223)

`CACHE_LINE_SIZE` defaults to 128 only on Apple AArch64 and to 64 otherwise,
unless supplied by the build. (src/config.h:38-43)

## Admission: which dispatches pin

After command state has moved from the real client to its fake, dispatch calls
`flatGroupPinEnter(fake)` only when all of the following coded conditions hold:
atomic mode is nonzero; `fake->cmd` is non-null; the command route contains
`TOMO_R_CROSS`; and either the command has `CMD_READONLY`, or atomic-write
admission succeeded and the route contains `TOMO_R_ATOMIC_READ`.
(src/server.c:8450-8469)

Immediately after entry, dispatch acquire-loads `commit_seq` into
`fake->tomo_read_snapshot`. Later pipeline and cross-shard constructors copy
that snapshot into the group's `read_seq` and mark `snapshot_pinned` when the
head fake carries the pin. (src/server.c:8465-8471,
src/server.c:12949-12956, src/server.c:13527-13640,
src/server.c:14326-14343,
src/server.c:14405-14415)

`tomoPinnedReadSnapshot()` resolves a snapshot from the executing client itself,
then from its parent group's copied snapshot, then from the group's pinned head;
if none applies, it reports no pinned snapshot. Versioned read lookup calls that
helper directly for the single-committed fast check. Its full resolver calls
`tomoCurrentReadSnapshot()`, which returns a pinned snapshot when one exists and
otherwise acquire-loads `commit_seq`.
(src/server.h:5881-5901, src/server.c:431-434,
src/db.c:366-395)

## Pin-entry protocol

`flatGroupPinEnter(fake)` performs the following exact operations. (src/server.c:1175-1200)

1. It reads thread-local `flat_slot_owned`, asserts that the identity is in the
   live IO range, and selects `ps = &flat_group_pins[s]`. IO-role registration
   sets `flat_slot_owned` only after asserting the same range and that the thread
   is outside a nested external region. (src/server.c:1082-1099,
   src/server.c:1178-1181)
2. It spins on weak compare-exchange of `scan_lock` from zero to one, with
   acquire ordering on success and relaxed ordering on failure; after each
   failure it resets the local expected value to zero. (src/server.c:1182-1185)
3. It relaxed-fetch-adds one to `active` and retains the old value as
   `was_active`. (src/server.c:1186)
4. Only when `was_active == 0`, it relaxed-ORs this IO slot's bit into
   `flat_group_pin_mask`, executes a sequentially consistent fence, and later
   initializes `floor` to the selected generation with a relaxed store.
   (src/server.c:1187-1194)
5. It relaxed-loads `gen = flat_batches_closed_n`, then relaxed-fetch-adds one to
   `pin_out[gen & FLAT_PIN_GEN_MASK]`. (src/server.c:1192-1195)
6. It writes `gen` to the fake's `tomo_read_snapshot_gen`, sets
   `tomo_read_snapshot_pinned = 1`, release-stores zero to `scan_lock`, and calls
   `FLAT_PUBLISH_FENCE()`. That final macro is a no-op on x86/x86-64 and a
   sequentially consistent thread fence on other targets. (src/server.c:1105-1114,
   src/server.c:1195-1200)

The first-pin mask publication and retire-batch generation increment are
sequentially consistent peers: batch close executes a sequentially consistent
fence and then a sequentially consistent fetch-add of
`flat_batches_closed_n`, returning the old value as that batch's `close_gen`.
(src/server.c:1175-1177, src/server.c:8969-8982)

## Pin-exit protocol

The IO reply drain releases a pin only on terminal retirement of that fake. A
multi-stage cross-shard head that launches another stage breaks out of the drain
before the release call, so the pin remains live across dispatch, worker
execution, intermediate completion, and final reassembly. (src/server.c:4285-4308,
src/server.c:4320-4341)

All three terminal drain shapes call `tomoReleaseReadSnapshot(fake)`: disconnected
client teardown, output-limit close, and ordinary successful retirement. The
helper returns immediately if the flag is clear; otherwise it clears the plain
flag and calls `flatGroupPinExit()`. (src/server.c:4045-4049,
src/server.c:4200-4207, src/server.c:4320-4341)

`flatGroupPinExit(fake)` performs this exact sequence. (src/server.c:1202-1216)

1. It resolves and range-asserts the current thread's `flat_slot_owned`, selects
   that per-IO slot, and reads the generation saved in the fake. (src/server.c:1202-1206)
2. It executes a release fence, relaxed-fetch-subtracts one from
   `pin_out[gen & 4095]`, and asserts that the old cell count was positive.
   (src/server.c:1207-1210)
3. It release-fetch-subtracts one from `active` and asserts that the old active
   count was positive. (src/server.c:1211-1212)
4. Only when that old value was one, it release-ANDs the slot's bit out of
   `flat_group_pin_mask`. (src/server.c:1213-1215)

## Reclaimer scan and blocking formula

Each retire batch receives `close_gen` from the old value of the sequentially
consistent increment of `flat_batches_closed_n`. `flatBatchReady()` calls
`flatGroupPinsBlock(close_gen)` before inspecting the ordinary inline-IO and
worker grace predicates, and treats a true result as “not ready.”
(src/server.c:8977-8982, src/server.c:9016-9058)

`flatGroupPinsBlock(close_gen)` applies this exact algorithm. (src/server.c:1218-1253)

1. It computes `hi = flatIoHi()` and `nwords = (hi + 64) >> 6`, then
   sequentially-consistent-loads each live word of `flat_group_pin_mask` and
   visits its set bits with `ctz`. Bits whose decoded slot is above `hi` are
   skipped. (src/server.c:1220-1227)
2. For each visited slot, it attempts one strong CAS of `scan_lock` from zero to
   one, using acquire ordering on success and relaxed ordering on failure. A
   failed CAS returns true immediately, conservatively blocking the batch.
   (src/server.c:1227-1231)
3. With the scan lock held, it acquire-loads current
   `flat_batches_closed_n`, relaxed-loads `floor`, acquire-loads `active`, and
   evaluates `pressure = (cur < floor) || (cur - floor >= 4096)` before changing
   the floor. (src/server.c:1232-1235)
4. If `active == 0`, it assigns `floor = cur`. Otherwise, only when
   `cur >= floor`, it advances `floor` while both `floor < cur` and the
   acquire-loaded cell `pin_out[floor & 4095]` is zero. It cannot step across a
   nonzero cell. (src/server.c:1236-1243)
5. It release-stores the resulting `floor`, then release-stores zero to
   `scan_lock`. (src/server.c:1244-1245)
6. If the previously computed `pressure` is true, it relaxed-increments
   `flat_pin_wrap_blocks` and returns true. Otherwise it returns true when
   `active != 0 && floor <= close_gen`; if neither condition holds, it continues
   scanning other engaged slots and finally returns false. (src/server.c:1246-1253)

The 4,096-generation bound is deliberately fail-safe: when `cur - floor` reaches
the ring width, a counter cell may be ambiguous because its index can be reused,
so the coded `pressure` branch blocks reclamation and records the event instead
of treating an ambiguous cell as quiescent. (src/server.c:985-992,
src/server.c:1218-1249)

Both per-worker reclaim and the main/table reclaim path feed retire-batch FIFO
heads through the same `flatBatchReady()` predicate, so group pins gate both
places that physically free ready FLAT retire batches. (src/server.c:9095-9131,
src/server.c:9181-9233)

## Memory-order map

| Edge | Exact ordering |
| --- | --- |
| First live pin versus batch close | First entry relaxed-sets the engaged mask bit and executes a seq-cst fence; close executes a seq-cst fence and seq-cst increments the generation. (src/server.c:1186-1195, src/server.c:8969-8982) |
| Pin entry versus floor scan | Both sides acquire `scan_lock`; entry release-unlocks after incrementing the selected cell, and scan release-unlocks after publishing `floor`. (src/server.c:1182-1199, src/server.c:1227-1245) |
| Pin contents before exit | Exit executes a release fence before its relaxed decrement of the saved generation cell, then release-decrements `active`. (src/server.c:1202-1215) |
| Engaged-slot discovery | Entry and exit update mask words with atomic RMWs; the scanner reads each live mask word with sequential consistency. (src/server.c:1186-1190, src/server.c:1211-1215, src/server.c:1220-1225) |
| Floor discovery | The scanner acquire-loads the global current generation and `active`, acquire-loads each tested `pin_out` cell, and release-stores the new floor. (src/server.c:1232-1245) |
| Snapshot frontier | Dispatch acquire-loads `commit_seq` only after pin entry has completed. (src/server.c:8465-8471) |

## Invariants enforced by the code

- Every admitted pin contributes one count to `active` and one count to exactly
  `pin_out[saved_generation & 4095]`; exit uses the generation stored on that
  same fake and asserts that both decremented old counts were positive.
  (src/server.c:1186-1197, src/server.c:1202-1212)
- On pin entry, only the `active` transition from zero sets the slot's mask bit
  and initializes its floor, and only the transition from one to zero clears that bit. Overlapping
  fakes on the same IO identity therefore share one engaged slot without erasing
  one another's pin. (src/server.c:1186-1195, src/server.c:1211-1215)
- `scan_lock` prevents a registration from selecting a generation and incrementing
  its cell while a reclaimer advances that slot's floor. A reclaimer that cannot
  obtain the lock blocks rather than scanning concurrently. (src/server.c:1175-1199,
  src/server.c:1218-1231)
- The reclaimer advances `floor` only across acquire-observed zero cells. Absent
  the independent `pressure` branch, an active slot blocks a batch exactly when
  its resulting floor is no newer than the batch's `close_gen`; `pressure` also
  blocks when `cur < floor` or `cur - floor >= 4096`. (src/server.c:1232-1251)
- Generation wrap cannot license a free: `cur < floor` or
  `cur - floor >= 4096` takes the conservative blocking branch. (src/server.c:1232-1249)
- The pin outlives every intermediate cross-shard stage and is dropped only by
  the owning IO drain's terminal fake-retirement paths. (src/server.c:4285-4308,
  src/server.c:4320-4341)

## Observability and callers

| Function or state | Use of the mechanism |
| --- | --- |
| `processCommand()` dispatch block | Calls `flatGroupPinEnter()` for the exact cross-shard atomic-read predicate, then captures the MVCC frontier. (src/server.c:8450-8471) |
| `tomoPinnedReadSnapshot()` and `lookupKeyReadWithFlags()` | Recover the dispatch snapshot for a direct fake, a cross-shard sub, or its group head and apply it to version selection. (src/server.h:5881-5901, src/db.c:366-395) |
| `handleWorkerReplies()` | Retains the pin through intermediate stages and calls the exit helper at terminal fake retirement, including disconnect and output-limit paths. (src/server.c:4188-4207, src/server.c:4285-4341) |
| `flatBatchReady()` | Blocks physical batch reclamation when `flatGroupPinsBlock()` reports a live, busy, or generation-ambiguous slot. (src/server.c:9016-9058) |
| INFO stats | Exposes identities with either inline or group pins, the close-generation backlog behind the oldest active floor, and the wrap-block counter as `tomokv_flat_io_pinned`, `tomokv_flat_pin_backlog`, and `tomokv_flat_pin_wrap_blocks`. (src/server.c:1017-1035, src/server.c:19206-19217) |
