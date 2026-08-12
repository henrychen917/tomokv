# FLATSTORE QSBR grace determination

How a retired value's grace is decided: the per-IO-identity `flat_epoch` odd/even encoding,
`flatExternEnter/Exit` depth-nesting, the per-worker `loop_seq` + `in_flat_section` signals, the
snapshot stamped at batch close, and the exact "every constituency has passed its grace or is
outside a protected section" computation in `flatBatchReady`. The FIFO drain, budget, and payload
dispatch live in `reclaim-budget.md`. References are to the pinned tree (`src/`); code is
authoritative over comments.

## The four reader constituencies

A retired kvobj may still be held by a lock-free reader. A batch may free only once every one of
these has demonstrably dropped its pointer:

1. **IO identities** running inline commands — SAVE, DEBUG DIGEST/RELOAD, EVAL, DEBUG SLEEP,
   activeExpire, evictions — announce via a per-identity `flat_epoch`.
2. **Workers** running an `exSlice` batch announce via `loop_seq` + `in_flat_section`.
3. **Unregistered threads** (module background, any pthread with no `iotid`) take a global fail-safe
   pin `flat_foreign_active`.
4. **Dispatch-lifetime group pins** (cross-shard MGET/SETOP reassembly, atomic-mode reads) hold a
   close-generation floor.

## IO identity epoch (constituency 1)

### Storage (`src/server.c:654-667,789`)

Each IO identity owns one cache-line-aligned `tmIoSignal` in `tm_io_sig[TOMO_IO_THREADS_MAX + 1]`.
Its QSBR word is the first field, alone on line 0:

```c
_Atomic uint64_t flat_epoch;   /* EVEN => OUTSIDE; ODD => INSIDE; 0 (BSS) => never entered, outside */
```

Written **only** by the owning thread, read by the grace machinery. A `_Static_assert` keeps it off
the line holding hot-written counters like `q_full_events` (`src/server.c:781-783`).

### TLS state (`src/server.c:1073-1080`)

```c
#define FLAT_SLOT_WORKER (-1)   /* quiescence via loop_seq/in_flat_section */
#define FLAT_SLOT_NONE   (-2)   /* unregistered: bio, module bg, anything with no iotid */
static __thread int      flat_extern_depth;            /* region nesting depth (all threads) */
static __thread int      flat_slot_owned = FLAT_SLOT_NONE; /* io slot this thread may publish */
static __thread int      flat_epoch_slot = -1;         /* slot LATCHED at outermost enter */
static __thread uint64_t flat_epoch_val;               /* the ODD value published at that enter */
static __thread int      flat_foreign_held;            /* 1 => holds the global pin */
```

Identity is claimed at every `iotid` assignment: `flatRegisterIoSlot(slot)` (main takes slot 0 at
`src/server.c:5936`) or `flatRegisterWorker()`; both assert `flat_extern_depth == 0` — identity may
never change inside a region (`src/server.c:1095-1103`).

### The IO constituency bound (`src/server.c:1086-1089`)

```c
static inline int flatIoHi(void) {
    int hi = server.io_threads + server.tm_ngrow_io;
    return hi > TOMO_IO_THREADS_MAX ? TOMO_IO_THREADS_MAX : hi;
}
```

Boot-fixed membership; every writer and reader uses this single expression, so the reader
constituency can never be narrower than the writer set.

### Enter / exit (`src/server.c:1125-1150`)

```c
static inline void flatExternEnter(void) {
    if (++flat_extern_depth != 1) return;              /* NESTED: publish nothing */
    int s = flat_slot_owned;
    if (s == FLAT_SLOT_WORKER) return;                 /* worker: loop_seq/in_flat_section covers it */
    if (s == FLAT_SLOT_NONE) { flatExternForeignEnter(); return; }
    uint64_t v = (load_relaxed(tm_io_sig[s].flat_epoch) | 1ULL) + 2;   /* ALWAYS odd, ALWAYS > cur */
    flat_epoch_slot = s;                               /* LATCH: exit must not re-resolve identity */
    flat_epoch_val  = v;
    store_seq_cst(tm_io_sig[s].flat_epoch, v);
    FLAT_PUBLISH_FENCE();                              /* no-op on x86; seq_cst fence elsewhere */
}
static inline void flatExternExit(void) {
    if (--flat_extern_depth != 0) return;              /* inner scope of a nested region */
    if (flat_foreign_held) { flatExternForeignExit(); return; }
    int s = flat_epoch_slot;
    if (s < 0) return;                                 /* worker, or nothing published */
    store_release(tm_io_sig[s].flat_epoch, flat_epoch_val + 1);   /* -> EVEN */
    flat_epoch_slot = -1;
}
```

Exact semantics:

- **Nesting is depth-counted**: only the outermost enter (`depth 0->1`) publishes; only the
  outermost exit (`depth 1->0`) clears. Nested `EXEC`/Lua/`RM_Call` regions change only the TLS
  depth (`src/server.c:1126,1141`).
- **Entry value is `(cur | 1) + 2`** — *always* odd and *strictly greater* than `cur`. This is
  fail-safe: even if the "slot is even at an outermost enter" invariant were violated, the worst
  case is a spurious pin, never a false "outside" (`src/server.c:1130-1134`).
- **Exit publishes `flat_epoch_val + 1`** (the following even value) through the **latched** slot,
  never re-resolving thread identity (`src/server.c:1148`).
- Starting from the BSS zero, ordinary outer transitions are `0 -> 3 -> 4 -> 7 -> 8 ...` — entry is
  not a plain increment.
- **Odd = inside**, **even = outside**. A never-entered or vacated slot (an IO slot whose thread grew
  into the EX role) is frozen at an even value and passes every grace forever, with no
  registration/deregistration protocol (`src/server.c:1058-1064`).

Out-of-TU callers (db.c's `dbScan` flat arm) use the thin wrappers `flatQsbrRegionEnter/Exit`, and
`call()` uses the RAII guard `FLAT_EXTERN_REGION()` (`src/server.c:1163-1173`).

## Worker signals (constituency 2)

`exThread` carries two polled atomics (`src/server.h:2611-2612`):

```c
_Atomic int      in_flat_section;   /* 1 while inside an exSlice batch that may touch a flat table */
_Atomic uint64_t loop_seq;          /* heartbeat: +1, release-stored, every exSlice pass */
```

At the top of every `exSlice` pass (`src/server.c:21796-21798`):

```c
uint64_t next = load_relaxed(worker->loop_seq) + 1;
store_release(worker->loop_seq, next);           /* QSBR quiescence signal */
```

Then, after arming the retire sink and running reclaim, the worker announces its section and parks
if a resize is active (`src/server.c:21827-21842`); the sole `exSlice` return seq-cst clears it
(`src/server.c:22361-22363`):

```c
store_seq_cst(worker->in_flat_section, 1);
while (load_seq_cst(server.flat_resize_active)) {
    store_seq_cst(worker->in_flat_section, 0);   /* back out so the coordinator can drain */
    ... wait ...
    store_seq_cst(worker->in_flat_section, 1);   /* re-enter, re-check */
}
...
store_seq_cst(worker->in_flat_section, 0);       /* single return covers every exit path */
```

`loop_seq` advancing past a snapshot means any reader that acquire-loaded the old pointer before the
retire has since finished a full pass (release here happens-before the reclaimer's acquire).

## The snapshot stamped at close (`src/server.c:8955-9001`)

`flatBatchClose` seals a retire list into a `flatBatch` whose flexible `arr[]` is three runtime-sized
regions addressed by macros (`src/server.c:8949-8953`, sizes set at init `src/server.c:22825-22826`):

```c
static int flat_batch_slots;       /* = server.io_threads + server.num_workers + 1 */
static int flat_batch_mask_words;  /* = (flat_batch_slots + 63) / 64 */
#define FB_SNAP(b)   ((b)->arr)                     /* uint64_t[flat_batch_slots]  worker loop_seq */
#define FB_IOSNAP(b) ((b)->arr + flat_batch_slots)  /* uint64_t[flat_batch_slots]  io flat_epoch */
#define FB_IOPIN(b)  ((b)->arr + 2*flat_batch_slots)/* uint64_t[flat_batch_mask_words] io_pin bits */
```

Close sequence, in order:

1. `b->nworkers = server.num_workers` (`src/server.c:8965-8966`).
2. **Mandatory `atomic_thread_fence(memory_order_seq_cst)`** (`src/server.c:8977`) — the StoreLoad
   barrier pairing the earlier release-unlink of every value in this batch against the snapshot loads
   below. Without it, on x86 the unlink store and the snapshot loads could both be stale ⇒ premature
   free.
3. `b->close_gen = fetch_add_seq_cst(flat_batches_closed_n, 1)` — the generation this close seals;
   the seq-cst RMW also pairs with group-pin `0->1` mask publication (`src/server.c:8981`).
4. **Worker snapshot**: `snap[w] = load_acquire(exThreads[w].loop_seq)` for `w < nworkers`
   (`src/server.c:8983-8984`).
5. **IO snapshot**: clear all `flat_batch_mask_words` of `io_pin`, then for each `t <= flatIoHi()`
   load the epoch seq-cst; **only if odd** record `io_snap[t] = v` and set bit `t` in `io_pin`
   (`src/server.c:8993-8997`):

```c
for (int t = 0; t <= io_hi; t++) {
    uint64_t v = load_seq_cst(tm_io_sig[t].flat_epoch);
    if (v & 1) { io_snap[t] = v; io_pin[t >> 6] |= 1ULL << (t & 63); }
}
```

An even IO slot holds nothing at close, so it is omitted from the mask — anything it enters later
reads a table these values were already unlinked from.

## The exact ready predicate (`src/server.c:9016-9059`)

`flatBatchReady` reaches `return 1` only when **all** clauses pass. `FLAT_QSBR_MARGIN` = `2`
(`src/flatstore.h:69`) is used by the worker clause only.

```text
foreign_active != 0 (seq_cst)                 -> return 0   (constituency 3)
flatGroupPinsBlock(close_gen) != 0            -> return 0   (constituency 4)
for each bit t set in io_pin:                              (constituency 1)
    flat_epoch[t] (acquire) == io_snap[t]     -> return 0   (still inside the SAME region)
for each w in [0, nworkers):                              (constituency 2)
    loop_seq[w] (acquire) >= snap[w] + 2      -> this worker passes
    else in_flat_section[w] (seq_cst) == 0    -> this worker passes
    else                                      -> return 0
return 1
```

### "Even-or-advanced," computed per constituency

- **IO slot passes** iff its `io_pin` bit is **clear** (it was even/outside at close) **or** its
  current epoch **differs** from `io_snap[t]` (it left — exited, or exited and re-entered — since the
  epoch advances only at an outermost enter and an outermost exit, both points where it holds no raw
  flat pointer) (`src/server.c:9037-9044`). Only "still the exact odd value it was at close" blocks.
- **Worker passes** iff `loop_seq` advanced by the margin of two past the snapshot **or** it is not
  currently in a flat section (holds nothing). Worker *liveness* is **not** a bypass — the loop
  covers all `b->nworkers`, deliberately not filtered by a live-worker predicate, because a
  converting EX→IO worker still runs straggler subs that deref the table (`src/server.c:9045-9057`).

The margin-of-2 (not 1) matters: a worker mid-pass may have already bumped `loop_seq` before entering
the section that reads the retired pointer, so one increment does not prove a full quiescent pass.

## Unregistered fail-safe pin (constituency 3)

`flat_foreign_active` is a cache-line-isolated `_Atomic int` (`src/server.c:982-983`). A thread with
no registered slot takes it seq-cst on outer enter and releases it on outer exit
(`src/server.c:1151-1162`); a non-zero value fails **every** batch's readiness immediately
(`src/server.c:9031`) — this is the exact old flag behaviour, and is ~always zero in this fork. It
carries no batch snapshot, so any foreign reader active at check time blocks even batches closed
before it entered.

## Dispatch-group pins (constituency 4)

Group pins cover whole dispatch/reassembly lifetimes using close generations rather than epoch
nesting (`src/server.c:985-1010,1178-1254`). Each `flatGroupPinSlot` (`src/server.c:993-1000`) has
cache-line-separated `_Atomic uint64_t active`, `_Atomic uint64_t floor`, `_Atomic int scan_lock`,
and a `_Atomic uint64_t pin_out[FLAT_PIN_GEN_WIDTH]` ring (`FLAT_PIN_GEN_WIDTH = 4096`); the fake
client records `tomo_read_snapshot_gen` and `tomo_read_snapshot_pinned` (`src/server.h:1912,1923`).

`flatGroupPinsBlock(close_gen)` (`src/server.c:1220-1254`) walks `flat_group_pin_mask`, and for each
engaged slot: **fails closed** (returns 1) if it cannot acquire `scan_lock`; advances the slot's
`floor` across zeroed generation cells; computes ring pressure `cur < floor || cur - floor >=
FLAT_PIN_GEN_WIDTH` (returns 1, `flat_pin_wrap_blocks++`, if set); and finally blocks iff
`active && floor <= close_gen`. So while a live pin's floor is generation `g`, it blocks batches with
`close_gen >= g` and does not block older batches below `g` (`src/server.c:1192-1196,1232-1250`).

## Invariants

- Only the outermost external scope publishes/clears an epoch; identity cannot change while nesting
  depth is non-zero (`src/server.c:1097-1103,1126,1141`).
- Registered IO entry always publishes an odd value greater than the loaded one; exit publishes the
  next even value via the latched slot (`src/server.c:1130-1148`).
- A batch cannot free while a captured IO slot still holds the exact odd epoch seen at close; an even
  slot at close is omitted from the mask (`src/server.c:8994-8997,9037-9044`).
- Every provisioned worker must advance by 2 or currently publish `in_flat_section == 0`; liveness is
  not a bypass (`src/server.c:9050-9057`).
- The close StoreLoad fence orders every batch value's release-unlink before the snapshot loads
  (`src/server.c:8969-8977`).

## Code / comment discrepancies

- The FLATSTORE file header describes a worker-`loop_seq` grace (its "main-thread" reclaim wording is at `src/flatstore.c:130-131`, not the :14-20 header) (`src/flatstore.c:14-20`).
  The ready predicate additionally gates on the global foreign pin, group generations, and captured
  IO epochs — four constituencies, not one (`src/server.c:9016-9058`).
- The close comment says every batch value "was unlinked with a RELEASE store (flatOverwrite /
  flatDelete) BEFORE this point" (`src/server.c:8969-8970`). A version-prune payload is intentionally
  queued while its anchor is still live, and a vmeta payload follows `kvobjSetVmeta(...,NULL)`, not a
  flat-slot unlink — the fence is real but that universal provenance claim is not (see
  `reclaim-budget.md`).
- `nworkers` is called "clamp defensively to num_workers" (`src/server.c:8963-8966`), but the
  executable assignment is exactly `int nw = server.num_workers; b->nworkers = nw;` with no clamp
  branch.
- `flat_batch_slots` is equated with "the largest reachable `io_hi + 1`" (`src/flatstore.h:87-97`),
  but the allocation uses the conservative `io_threads + num_workers + 1` while the reader bound uses
  the current `flatIoHi()` = `io_threads + tm_ngrow_io` (`src/server.c:8944-8953,1086-1089`).

## File / line map

| Item | Location |
|---|---|
| `flat_epoch` storage + odd/even doc | `src/server.c:654-667` |
| Reader TLS + slot registration | `src/server.c:1073-1103` |
| `flatIoHi` constituency bound | `src/server.c:1086-1089` |
| `flatExternEnter` / `flatExternExit` | `src/server.c:1125-1150` |
| Foreign pin enter/exit | `src/server.c:1151-1162` |
| Worker `loop_seq` + `in_flat_section` announce | `src/server.c:21796-21842`, `src/server.c:22361-22363` |
| Batch snapshot regions (FB_* macros) | `src/server.c:8949-8953`, `src/server.c:22825-22826` |
| `flatBatchClose` (fence, gen, snapshots) | `src/server.c:8955-9001` |
| `flatBatchReady` predicate | `src/server.c:9016-9059` |
| `FLAT_QSBR_MARGIN = 2` | `src/flatstore.h:69` |
| Group-pin slots + `flatGroupPinsBlock` | `src/server.c:993-1010,1178-1254` |
