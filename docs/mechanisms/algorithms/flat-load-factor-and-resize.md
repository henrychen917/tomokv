# FLATSTORE load factor, resize triggers, and grow/shrink sizing

The `FLAT_LOAD_PCT = 70` load trigger, the monotonic `NONE/NORMAL/URGENT` request, the
grow-vs-shrink target selection in `flatTableAllocFor`, the delete-side shrink trigger, and the
insert-full URGENT escalation + wait path. References are to the pinned tree (`src/`); code is
authoritative over comments.

## Constants (`src/flatstore.h:33-46`)

| Name | Value | Meaning |
|---|---|---|
| `FLAT_LOAD_PCT` | `70ULL` | target peak load %; the rebuild trigger |
| `FLAT_MIN_SIZE` | `1ULL << 18` = 262144 | initial size **and** shrink floor (2 MB @ 8B) |
| `FLAT_INSERT_FULL` | `UINT64_MAX` | insert exhausted every slot |
| `FLAT_RESIZE_NONE` | `0` | no request |
| `FLAT_RESIZE_NORMAL` | `1` | load / tomb / shrink-triggered rebuild |
| `FLAT_RESIZE_URGENT` | `2` | an insert is blocked on a full table |

`FLAT_LOAD_PCT` is a compile-time constant (was the retired `tomokv-flat-load-pct` knob), not a
per-insert load from a server global (`src/flatstore.h:35-40`).

## The request field and its monotonic raise (`src/flatstore.c:88-94`)

`flatTable.resize_needed` is `_Atomic int` (`src/flatstore.h:116`). `flatResizeRequest` raises it
with a relaxed weak-CAS loop that only ever **increases** the level:

```c
serverAssert(level > FLAT_RESIZE_NONE && level <= FLAT_RESIZE_URGENT);
int current = load_relaxed(resize_needed);
while (current < level &&
       !CAS_weak(resize_needed, &current, level, relaxed, relaxed)) { }
```

So a `NORMAL` request can never downgrade an `URGENT` one. The coordinator clears the request only
by **replacing the table** (a fresh table starts at `NONE`, `src/flatstore.c:80`,
`src/server.c:9436`).

## Trigger 1 — insert grow (`src/flatstore.c:252-256`)

After a successful insert CAS, with `u` = post-increment `used` and a relaxed reload of `tombs`:

```c
if ((u + load_relaxed(tombs)) * 100 >= t->size * FLAT_LOAD_PCT)
    flatResizeRequest(t, FLAT_RESIZE_NORMAL);
```

Trigger condition (integer arithmetic, no division): **`(used + tombs) * 100 >= size * 70`**, i.e.
the table crosses 70% occupancy counting live slots **and** tombstones. This is the only place tombs
enter the grow decision.

## Trigger 2 — delete shrink (`src/flatstore.c:286-292`)

`flatDelete` release-stores the pure `FLAT_TOMB`, then relaxed `used--`, `tombs++`, then, with `nu`
= post-decrement `used`:

```c
if (t->size > FLAT_MIN_SIZE && nu * 400 <= t->size * FLAT_LOAD_PCT)
    flatResizeRequest(t, FLAT_RESIZE_NORMAL);
```

Shrink condition: **`size > FLAT_MIN_SIZE` and `used * 400 <= size * 70`**, i.e. live load
`used/size <= 70/400 = 0.175` (17.5%). Hysteresis vs the grow path: grow fires at 70%, the
post-grow load is ~35% (a doubling halves it), so 17.5% is well clear and the table does not
thrash between grow and shrink.

## Target selection — `flatTableAllocFor` (`src/flatstore.c:296-321`)

Sizes the replacement from the **LIVE** count only (`used`), never `used + tombs`, so a trigger that
fired purely on tombstone accumulation rebuilds same-size to GC tombs rather than growing:

```c
uint64_t used = load_relaxed(old->used);
uint64_t target = old->size;
if (used * 200 >= old->size * FLAT_LOAD_PCT) {
    target = old->size * 2;                                  /* GROW: single doubling */
} else {
    while (target > FLAT_MIN_SIZE && (target >> 1) * FLAT_LOAD_PCT >= used * 200)
        target >>= 1;                                        /* SHRINK: repeated halving */
}
flatTable *nw = flatTableNew(target);
nw->gen = old->gen + 1;
return nw;
```

- **Grow decision**: `used * 200 >= old_size * 70` ⇔ live load `used/old_size >= 70/200 = 0.35`
  (35%). When true, `target = old_size * 2` — **exactly one doubling**. A resize at load `T`
  intrinsically lands at `T/2` after copy (since `used <= old_size`), so one double always suffices.
- **Shrink loop**: while `target > FLAT_MIN_SIZE` **and** `(target>>1) * 70 >= used * 200` (halving
  would still keep live load `<= 35%`), halve. This permits multi-step shrink toward the smallest
  power-of-two that holds `used` at `<= 35%`, floored at `FLAT_MIN_SIZE`.
- **Same-size rebuild** (tomb GC): if neither the grow condition nor the first halving condition
  holds, `target` stays `old->size` — the table is rebuilt to reclaim tombstones without changing
  size. The steady state oscillates ~`(35% .. 70%)` load.

`nw->gen = old->gen + 1` bumps the generation so a cursor carrying `gen` restarts on the change
(`src/flatstore.h:112`, `src/flatstore.c:319`).

`flatTableNew(want_size)` rounds up to a power of two starting from **1024**, not `FLAT_MIN_SIZE`
(`src/flatstore.c:71-73`): `sz = 1024; while (sz < want_size) sz <<= 1`. Direct calls below 1024
still allocate 1024 slots; the ordinary kvstore-create path passes `FLAT_MIN_SIZE`
(`src/kvstore.c:347-350`).

## Insert-full → URGENT escalation and the wait path

When `flatInsert` returns `FLAT_INSERT_FULL`, the kvstore new-item adapter escalates and fails the
call (`src/kvstore.c:1109-1114`):

```c
uint64_t inserted = flatInsert(t, h, masked, slot);
if (inserted == FLAT_INSERT_FULL) {
    flatResizeRequest(t, FLAT_RESIZE_URGENT);
    if (link) *link = NULL;      /* a resize invalidates the old table's link */
    return DICT_ERR;
}
```

`dbSetAtLinkWithFlatRetry` (`src/db.c:529-557`) loops until `DICT_OK`. On each `DICT_ERR`:

1. Snapshot the current table's `used`/`tombs` (relaxed) and `size` while still inside the flat
   section (so the table cannot be replaced mid-diagnostic) (`src/db.c:538-542`).
2. If `wait_rounds == FLAT_INSERT_MAX_WAIT_ROUNDS` (= `64`, `src/db.c:504`), **panic** with the
   captured counts. Rounds 0..63 proceed to wait, so the panic is on the **65th** failed attempt
   (`src/db.c:544-547`).
3. Derive/range-check the worker identity (`owner = iotid - (TOMO_IO_THREADS_MAX + 1)`), relaxed
   `flat_insert_full_waits++`, and call `dbFlatInsertWait(&server.exThreads[owner])`
   (`src/db.c:549-552`).

`dbFlatInsertWait` (`src/db.c:512-527`) is the owner-lock + flat-section handshake:

- Drop the owner publication lock (`tomoWkrUnlockPub`).
- Loop: seq-cst clear `in_flat_section = 0`; if `flat_resize_active` is not yet set, `usleep(100)`
  to give main's coordinator a chance to observe the urgent request; call `tomoFlatResizeQuiesce()`.
- Reacquire the owner lock, seq-cst publish `in_flat_section = 1`, and if a seq-cst load still sees
  `flat_resize_active`, unlock and repeat; otherwise return with both protections held.

The next loop attempt reloads `flatCurrent` (the link was cleared) and reruns the write search
against the replacement table (`src/db.c:554-556`, `src/kvstore.c:1101-1108`).

`tomoFlatResizeQuiesce` (`src/server.c:15500-15522`) returns immediately unless
`server.shared_node_dbs`; it relaxed-increments `flat_rz_quiesce_waits` once if resize was active at
entry, then waits while `flat_resize_active` stays true — main (`iotid == 0`) drives
`flatResizeCoordinate()` inside the loop, off-main identities call `flatResizeWatchdog()`, and every
iteration `usleep(100)`.

## The coordinator's use of the request (`src/server.c:9339-9448`)

The `beforeSleep` coordinator (see `qsbr-grace.md` for the QUIESCING drain) scans tables **URGENT
before NORMAL** (`src/server.c:9346-9356`), copies in `FLAT_RZ_COPY_SLOT_BUDGET = 1<<16` slot chunks
per pass (`src/server.c:9273,9432`), and on completion: relaxed-counts `flat_rz_urgent_services++`
if the old request is still `>= URGENT`, relaxed-clears the new table's request to `NONE`,
`kvstoreFlatSwap`s the replacement in, and retires the old table (`src/server.c:9434-9442`).

## Invariants

- `resize_needed` is monotone non-decreasing until cleared by table replacement; `NONE` on a fresh
  table (`src/flatstore.c:80,88-94`, `src/server.c:9436`).
- Grow is at most one doubling; shrink never goes below `FLAT_MIN_SIZE`; tomb-only triggers rebuild
  same size (`src/flatstore.c:301-317`).
- Target is a function of `used` alone, independent of the request level or `tombs`
  (`src/flatstore.c:301`).
- The grow trigger reads `used + tombs` at 70%; the shrink trigger reads `used` alone at 17.5%; the
  sizing boundary is 35% live — three distinct thresholds.

## Code / comment discrepancies

- **Sizing comment vs code (`src/flatstore.c:296-308`).** The comment says the target lands "<= 1/3
  live," says "double (or more)," says "Never shrink below `old->size`," and refers to a "0.5
  trigger." The code instead: lands `<= 0.35` live (35% boundary), grows by **exactly one** doubling,
  **can shrink** repeatedly below `old->size` (down to `FLAT_MIN_SIZE`), and receives ordinary insert
  requests at 70% `used+tombs`, not 0.5.
- **"the table is not yet full (0.5 trigger)"** in the coordinator deadline path
  (`src/server.c:9406`) refers to the same stale 0.5 figure; the live grow trigger is 70%
  `used+tombs` (`src/flatstore.c:255`).

## File / line map

| Item | Location |
|---|---|
| Load / size / request constants | `src/flatstore.h:33-46` |
| Monotonic `flatResizeRequest` | `src/flatstore.c:88-94` |
| Insert grow trigger (70% used+tombs) | `src/flatstore.c:252-256` |
| Delete shrink trigger (17.5% used) | `src/flatstore.c:286-292` |
| Grow/shrink/same-size selection | `src/flatstore.c:296-321` |
| `flatTableNew` (1024 floor, pow2) | `src/flatstore.c:71-86` |
| Insert-full → URGENT + `DICT_ERR` | `src/kvstore.c:1109-1114` |
| Retry loop + panic-at-65 | `src/db.c:504,529-557` |
| Owner-lock / flat-section wait | `src/db.c:512-527` |
| Quiesce helper | `src/server.c:15500-15522` |
| Coordinator URGENT-first + copy budget | `src/server.c:9346-9356,9431-9442` |
