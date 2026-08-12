# FLATSTORE: the lock-free open-addressing hash table

## Scope and storage selection

FLATSTORE is the `KVSTORE_FLAT` branch of `kvstore`: it stores encoded `kvobj` pointers in a
power-of-two array of atomic 64-bit slot words and resolves collisions by linear probing without a
slot lock (`src/kvstore.h:86-100`, `src/flatstore.h:56-58`, `src/flatstore.c:207-237`). The branch is
selected by flag bit `1 << 3`; `kvstoreIsFlat()` tests that bit, and the current table pointer is
acquired from `_kvstore.flat`
(`src/kvstore.h:99-107`, `src/kvstore.c:39-56`, `src/kvstore.c:77-85`).

When `server.shared_node_dbs` is true, each initialized physical node database has both
`KVSTORE_SHARED_MT` and `KVSTORE_FLAT` added to its key-store flags, while its expiry store has
`KVSTORE_FLAT` removed; the logical `server.db` entry is initialized without either shared-store flag
(`src/server.c:5561-5585`). `kvstoreCreate()` still allocates the `dicts` pointer array, but a flat
store additionally creates `flatTableNew(FLAT_MIN_SIZE)` (`src/kvstore.c:339-350`). The physical
flat stores also have `KVSTORE_ALLOCATE_DICTS_ON_DEMAND`, so creation does not instantiate the
per-index dictionaries; normal find/set calls branch to the flat table
(`src/server.c:5567-5579`, `src/kvstore.c:342-350`, `src/kvstore.c:1025-1029`,
`src/kvstore.c:1075-1079`, `src/kvstore.c:1099-1130`).

## Data structures

### The slot word

`flatSlot` has one field, `_Atomic uint64_t w` (`src/flatstore.h:56-58`). The executable predicates
interpret that word as follows (`src/flatstore.h:33-54`):

| Bits | Meaning implemented by the macros | Source |
|---|---|---|
| `[63:49]` | A 15-bit tag. `FLAT_TAG_SHIFT` is 49, `flat_tag_of(h)` is `(h >> 49) & 0x7fff`, and `flat_word_tag(w)` applies the same mask to a word. | `src/flatstore.h:48-50` |
| `[48]` | `FLAT_TOMB`, whose value is `0x0001000000000000`. | `src/flatstore.h:47` |
| `[47:0]` | The stored masked pointer. `FLAT_PTR_MASK` is `0x0000ffffffffffff`, and `flat_word_ptr(w)` discards every higher bit. | `src/flatstore.h:33`, `src/flatstore.h:51` |

`flat_make(h, mp)` combines the 15-bit tag with only the low 48 bits of `mp`; it does not set the
tomb bit (`src/flatstore.h:49-52`). `FLAT_IS_EMPTY(w)` is true only for the exact word zero, whereas
`FLAT_IS_LIVE(w)` tests only whether the low 48 pointer bits are nonzero (`src/flatstore.h:53-54`).
Consequently, any nonzero pointerless word is a reusable, non-stopping dead state, and even a word
with the tomb bit set is classified as live if its pointer bits are nonzero
(`src/flatstore.h:47-54`, `src/flatstore.c:211-218`, `src/flatstore.c:227-230`).

The insert path asserts that its encoded pointer has no bits above bit 47 before constructing the
word (`src/flatstore.c:239-244`). The pointer is encoded by `dictEncodeStoredKey()` in the kvstore
adapter, and key comparison decodes it with `dictGetKV()` before comparing the embedded key's
length and bytes (`src/kvstore.c:70-76`, `src/flatstore.c:199-205`).

### Table and retirement records

| Type | Fields and code-visible role | Source |
|---|---|---|
| `flatRetireNode` | `masked_kv` and `next`; these nodes carry deferred payloads. | `src/flatstore.h:67`, `src/flatstore.c:168-185` |
| `flatBatch` | `head`, `close_gen`, `nworkers`, `next`, and flexible `uint64_t arr[]`. | `src/flatstore.h:98-104` |
| `flatTable` | `slots`, power-of-two `size`, and `mask == size - 1`. | `src/flatstore.h:106-109`, `src/flatstore.c:71-77` |
| `flatTable` | Atomic `used` and `tombs` counters. All updates used by the core operations are relaxed and occur after the slot transition. | `src/flatstore.h:110-111`, `src/flatstore.c:250-255`, `src/flatstore.c:283-287` |
| `flatTable` | `gen`, initialized to zero and set to `old->gen + 1` for a rebuilt table. | `src/flatstore.h:112`, `src/flatstore.c:80-84`, `src/flatstore.c:318-320` |
| `flatTable` | Atomic `retire_stack`, pointers `batches`/`batches_tail`, and atomic `resize_needed`. | `src/flatstore.h:113-117`, `src/flatstore.c:80-84` |
| `_kvstore` | `flags` selects the implementation, `_Atomic(flatTable *) flat` publishes the current table, `dtype` is passed to `dictEncodeStoredKey()`, and `key_count` is relaxed-incremented after a successful flat kvstore insert. | `src/kvstore.c:39-56`, `src/kvstore.c:74-85`, `src/kvstore.c:1115-1116` |

`flatTableNew(want_size)` starts at 1,024 slots and doubles until `size >= want_size`, zero-allocates
the slot array, sets `mask = size - 1`, initializes `used`, `tombs`, `resize_needed`, and
`retire_stack` with relaxed stores, and clears the generation and batch pointers
(`src/flatstore.c:71-85`). Thus direct calls with a request below 1,024 still allocate 1,024 slots;
the ordinary kvstore creation path passes `FLAT_MIN_SIZE == 1 << 18` instead
(`src/flatstore.c:71-73`, `src/flatstore.h:33-40`, `src/kvstore.c:347-350`).

## Lookup and write protocol

### Lookup: `flatGet()`

1. A null table returns null; otherwise the probe starts at `h & t->mask` and advances with
   `(i + 1) & mask` for at most `mask + 1 == size` iterations (`src/flatstore.c:207-211`,
   `src/flatstore.c:219-220`).
2. Each slot word is loaded with `memory_order_acquire`. Exact zero terminates the search as absent;
   a dead nonzero word does not terminate it (`src/flatstore.c:210-218`).
3. A live word whose 15-bit tag matches causes pointer decoding and a full key check: equal SDS
   length followed by `memcmp`; a tag collision or different live tag continues the probe
   (`src/flatstore.c:199-205`, `src/flatstore.c:211-218`).

### Write search: `flatFindForWrite()`

1. The search uses the same home slot, wraparound, full-table bound, and acquire slot loads as
   `flatGet()`; it records the first non-live, nonempty word encountered
   (`src/flatstore.c:223-230`).
2. On an empty word it reports the key absent and returns the first recorded dead slot, or that
   empty slot if none was recorded (`src/flatstore.c:227-229`).
3. On a live matching tag it performs the full length-and-byte comparison; an exact key reports
   found and returns that live slot (`src/flatstore.c:230-233`).
4. After a complete wrap with no empty word or matching key, it reports absent and returns the first
   recorded dead slot, or the home slot when every examined word was live
   (`src/flatstore.c:234-237`).

The returned slot is only a hint, not a reservation: `flatFindLinkWithHash()` exposes it as a
`dictEntryLink` pointing at `&t->slots[slot].w`, and `flatInsert()` reloads the word and arbitrates
the claim with a compare/exchange (`src/kvstore.c:1060-1068`, `src/flatstore.c:245-252`).

### Insert: `flatInsert()`

1. The function starts at the caller's `hint_slot`, constructs `tag | low-48-bit-pointer`, and
   performs at most `size` loop iterations (`src/flatstore.c:239-246`, `src/flatstore.c:265-266`).
2. A live word advances to the next slot. For an empty or other non-live word, the function uses a
   strong CAS from the exact acquired word to the new word, with `memory_order_acq_rel` on success
   and `memory_order_acquire` on failure (`src/flatstore.c:247-264`).
3. A successful CAS relaxed-increments `used`; if the replaced word was nonzero, it also
   relaxed-decrements `tombs` (`src/flatstore.c:250-254`). It then requests a normal resize when
   `(post_increment_used + relaxed_tombs) * 100 >= size * FLAT_LOAD_PCT`, where
   `FLAT_LOAD_PCT == 70` (`src/flatstore.c:252-256`, `src/flatstore.h:35-40`).
4. After a failed CAS, `expect` contains the word observed when the comparison failed. A live
   `expect` advances the index; a non-live `expect` retries the same index, while the loop iteration
   is still consumed (`src/flatstore.c:249-262`).
5. Exhausting the loop returns `FLAT_INSERT_FULL == UINT64_MAX`; `flatInsert()` itself does not
   change `resize_needed` on that return (`src/flatstore.h:41`, `src/flatstore.c:239-267`).

### Overwrite: `flatOverwrite()`

`flatOverwrite()` relaxed-loads the selected word, saves its low-48-bit old pointer, preserves all
high 16 bits, substitutes the low 48 bits of the new pointer, and release-stores the result
(`src/flatstore.c:269-275`). It neither changes `used`/`tombs` nor retires the returned old pointer
(`src/flatstore.c:269-276`).

### Delete: `flatDelete()`

`flatDelete()` relaxed-loads the selected word, extracts its old pointer, release-stores the pure
`FLAT_TOMB` word, relaxed-decrements `used`, and relaxed-increments `tombs`
(`src/flatstore.c:278-287`). Because the stored value is the constant `FLAT_TOMB`, this transition
clears the old tag and pointer bits (`src/flatstore.h:47-52`, `src/flatstore.c:283-285`). It requests
a normal resize when `size > FLAT_MIN_SIZE` and the
post-decrement count satisfies `used * 400 <= size * FLAT_LOAD_PCT`, which is a live load of at most
17.5% for `FLAT_LOAD_PCT == 70` (`src/flatstore.c:286-292`, `src/flatstore.h:34-40`). The function
returns the old masked pointer but does not retire it (`src/flatstore.c:283-294`).

The tombstone cannot terminate a later search because it is nonzero, and it is reusable because it
has no pointer bits (`src/flatstore.h:47-54`, `src/flatstore.c:211-218`,
`src/flatstore.c:227-230`). Reusing any nonzero dead word replaces it with the new live word and
decrements `tombs` once (`src/flatstore.c:247-254`).

### Value removal and deferred destruction

The flat versions of `kvstoreDictTwoPhaseUnlinkFree()` and `kvstoreDictDelete()` call
`flatDelete()`, pass a non-null returned pointer through `flatDecodeKV()` to
`tomoRetireDetachedBag()`, and relaxed-decrement `kvs->key_count`
(`src/kvstore.c:1176-1183`, `src/kvstore.c:1191-1199`). For an unversioned object,
`tomoRetireDetachedBag()` calls `kvstoreFlatRetireRaw()`, which acquire-loads the current table,
encodes the raw pointer, and calls `flatRetire()` (`src/db.c:1112-1119`,
`src/kvstore.c:74-89`).

`flatRetire()` ignores a null payload. Otherwise its helper obtains a retire node, pushes it onto the
thread-local sink with plain pointer writes when `flat_local_sink` is set, or pushes it onto the
table's shared stack using a relaxed head load and a weak CAS with release success/relaxed failure
(`src/flatstore.c:168-188`). Once a closed batch passes the reader checks, `flatBatchFree()` calls
`flatRetirePayloadReady()` for each node; an ordinary, nonspecial payload then reaches
`decrRefCount(dictGetKV(payload))` (`src/server.c:9016-9058`, `src/server.c:9061-9077`,
`src/server.c:9095-9104`, `src/flatstore.c:43-51`).

## KVSTORE routing

The table pointer accessor uses an acquire load, and `kvstoreFlatSwap()` publishes a replacement
with a release store (`src/kvstore.c:78-85`). In the flat route, the generic kvstore operations work
as follows:

- `kvstoreDictFind()` ignores `didx`, hashes the SDS key with `tomoKeyHash()`, and calls `flatGet()`
  (`src/kvstore.c:1025-1029`).
- `kvstoreDictFindLink()` ignores `didx`, calls `flatFindForWrite()`, returns a found link only for an
  exact key, and puts the found-or-insert position in `bucket` when one was supplied
  (`src/kvstore.c:1060-1068`, `src/kvstore.c:1075-1079`).
- For `newItem != 0`, `kvstoreDictSetAtLink()` encodes the raw `kvobj`, recomputes its key hash, uses
  a supplied link as the initial slot or reruns `flatFindForWrite()`, then calls `flatInsert()`
  (`src/kvstore.c:1099-1109`). The fallback search's `found` result is ignored; preventing this route
  from being invoked for an existing key without a found-slot link is therefore a caller precondition
  (`src/kvstore.c:1106-1109`). A successful insert rewrites the link to the slot actually claimed
  and relaxed-increments `kvs->key_count` (`src/kvstore.c:1115-1116`). A link to an existing slot is
  also not valid for `newItem`: `flatInsert()` starts at that live slot, skips it, and searches for a
  different reusable slot (`src/flatstore.c:245-265`).
- If that insert returns `FLAT_INSERT_FULL`, the adapter raises `resize_needed` to
  `FLAT_RESIZE_URGENT`, clears the supplied link so it cannot refer to a replaced table, and returns
  `DICT_ERR` (`src/kvstore.c:1109-1114`).
- For `newItem == 0` and non-null `kv`, the adapter converts the link back to a slot index and calls
  `flatOverwrite()` without using its returned old pointer; for null `kv`, it hits an unconditional
  assertion instead of preclearing the slot (`src/kvstore.c:70-76`,
  `src/kvstore.c:1117-1128`).

## Full-table wait and retry

`dbSetAtLinkWithFlatRetry()` retries a new-item `kvstoreDictSetAtLink()` until it returns `DICT_OK`;
the flat adapter has already made the failed table's request urgent and cleared the stale link before
each `DICT_ERR` reaches this loop (`src/db.c:529-538`, `src/kvstore.c:1109-1114`). On a failure, the
loop snapshots the current table's `used` and `tombs` with relaxed loads and reads `size` while its
flat section still prevents replacement (`src/db.c:535-543`, `src/server.c:21819-21842`).

The retry protocol is:

1. `wait_rounds` starts at zero. If a failure is observed with `wait_rounds == 64`, the server panics
   with the captured counts; failures for rounds 0 through 63 proceed to wait, so the panic is on the
   65th failed insert attempt
   (`src/db.c:504`, `src/db.c:529-547`).
2. The code derives and range-checks the current worker identity, relaxed-increments
   `flat_insert_full_waits`, and calls `dbFlatInsertWait()` (`src/db.c:549-553`).
3. `dbFlatInsertWait()` drops the worker's owner publication lock, seq-cst-clears
   `in_flat_section`, sleeps 100 microseconds if `flat_resize_active` is not yet set, and calls
   `tomoFlatResizeQuiesce()` (`src/db.c:512-520`).
4. It reacquires the owner lock before seq-cst-publishing `in_flat_section = 1`; if a seq-cst load
   still sees resize active, it unlocks and repeats, otherwise it returns with both protections held
   (`src/db.c:521-526`).
5. The caller increments `wait_rounds` and retries. Because the adapter cleared `*link`, the next
   attempt acquire-loads the current table and reruns the write search before inserting
   (`src/db.c:529-556`, `src/kvstore.c:78-80`, `src/kvstore.c:1101-1109`).

`tomoFlatResizeQuiesce()` returns immediately when `server.shared_node_dbs` is false. Otherwise it
acquire-loads `flat_resize_active` at entry and relaxed-increments `flat_rz_quiesce_waits` once when
that initial value is true; it then waits only while acquire loads keep seeing the active flag true
(`src/server.c:15499-15510`). The main IO identity advances `flatResizeCoordinate()` inside that
loop; other identities call the resize watchdog, and every iteration sleeps 100 microseconds
(`src/server.c:15509-15522`).

## Target sizing and copy

`flatResizeRequest()` accepts only `NORMAL` or `URGENT`, relaxed-loads the current level, and uses a
relaxed weak CAS only while `current < requested`; a normal request therefore cannot lower an urgent
one on the same table (`src/flatstore.h:42-46`, `src/flatstore.c:88-94`).

`flatTableAllocFor(old)` reads `old->used` relaxed and chooses a power-of-two target from the live
count, not from the request level or `tombs` (`src/flatstore.c:296-320`):

- If `used * 200 >= old_size * FLAT_LOAD_PCT`—at least 35% live with the current constant—the target
  is exactly `old_size * 2` (`src/flatstore.c:301-310`, `src/flatstore.h:40`).
- Otherwise it repeatedly halves while `target > FLAT_MIN_SIZE` and
  `(target >> 1) * FLAT_LOAD_PCT >= used * 200`; this permits multi-step shrink but never executes a
  halving iteration once `target == FLAT_MIN_SIZE` (`src/flatstore.c:311-317`).
- If neither the grow condition nor the first halving condition holds, the target remains the old
  size, rebuilding it without tombstones (`src/flatstore.c:301-318`, `src/flatstore.c:323-335`).
- The new table is allocated with `flatTableNew(target)` and receives `old->gen + 1`
  (`src/flatstore.c:318-320`).

`flatTableCopyChunk()` scans the half-open range from `*cursor` through at most `slot_budget` old
slots, relaxed-loads each old word, and skips non-live words (`src/flatstore.c:323-329`). For each
live word it decodes the key, recomputes the full hash, finds a target slot, inserts the same masked
pointer, and asserts that the target did not return `FLAT_INSERT_FULL`; it advances the cursor and
returns whether the old table has been completely scanned (`src/flatstore.c:329-339`). The function
contains no writer exclusion of its own and uses relaxed old-slot loads; exclusion is supplied by the
server coordinator before it calls this function (`src/flatstore.c:323-338`,
`src/server.c:9379-9433`).

## Resize coordinator

The main event-loop `beforeSleep()` path runs retirement work and `flatResizeCoordinate()` whenever
`server.shared_node_dbs` is true (`src/server.c:4438-4460`). The coordinator uses the atomic states
`FLAT_RZ_IDLE`, `FLAT_RZ_QUIESCING`, and `FLAT_RZ_COPYING`, plus the selected kvstore/table pointers,
a copy cursor, an atomic arm timestamp, and node/database indexes (`src/server.c:9250-9264`).
Because `flat_rz_state` is `_Atomic`, its bare reads and assignments in the coordinator are implicit
sequentially consistent atomic operations; `flatResizeState()` is the explicit relaxed-load
exception (`src/server.c:9250-9259`, `src/server.c:9282`, `src/server.c:9342`,
`src/server.c:9375`, `src/server.c:9446`).

`flatResizePending()` returns true immediately when the state is not `IDLE`; in `IDLE`, it returns
true if any initialized physical table has a nonzero relaxed-loaded `resize_needed`, and returns
false when the shared node-database arrays are unavailable or no request is found
(`src/server.c:9325-9337`).

### `IDLE`: choose and arm

1. If the shared node-database arrays are unavailable, the coordinator returns
   (`src/server.c:9339-9341`). Otherwise it scans every initialized node/database table first for
   `resize_needed >= URGENT` and only then for `resize_needed >= NORMAL`
   (`src/server.c:9342-9357`).
2. It returns while migration or the flush gate is active, and it uses an acq-rel exchange to acquire
   `mig_arm_lock`; a nonzero previous value also makes it return (`src/server.c:9358-9362`).
3. It seq-cst-publishes `flat_resize_active = 1`, then seq-cst-rechecks the flush and migration gates.
   If either is now set, it seq-cst-clears the active flag, release-clears `mig_arm_lock`, and returns
   (`src/server.c:9363-9372`).
4. It records the selected objects, release-stores the arm time, seq-cst-assigns state `QUIESCING`,
   and returns before doing any copy (`src/server.c:9373-9376`).

### `QUIESCING`: drain or abort

1. Every worker's `in_flat_section` must seq-cst-load as zero. If they do, `flat_foreign_active` must
   also be zero and each IO identity through `flatIoHi()` must have an even `flat_epoch`; all of these
   checks are seq-cst (`src/server.c:9379-9401`).
2. If a participant remains and elapsed time is greater than 200,000 microseconds, the coordinator
   attempts `flatResizeAbortQuiesce()` and returns. That helper CASes `QUIESCING -> IDLE` with
   acq-rel/acquire ordering, seq-cst-clears `flat_resize_active`, and release-clears `mig_arm_lock`;
   it does not clear the old table's `resize_needed` (`src/server.c:9267`,
   `src/server.c:9297-9305`, `src/server.c:9402-9412`).
3. Once every participant is out, the coordinator CASes `QUIESCING -> COPYING` with
   acq-rel/acquire ordering. A lost CAS returns without allocating; a won CAS calls
   `flatTableAllocFor()`, zeros the cursor, and returns (`src/server.c:9414-9428`).

Workers participate by seq-cst-setting `in_flat_section = 1` before checking the seq-cst active flag.
While it is active they seq-cst-clear their section flag, wait until an acquire load sees it clear,
and then seq-cst-reenter and recheck; the sole exit from the worker slice seq-cst-clears the flag
(`src/server.c:21819-21842`, `src/server.c:22361-22364`).

Non-worker read regions do not test or park on `flat_resize_active`. An outermost registered reader
seq-cst-publishes an odd `flat_epoch` on entry and release-publishes the following even value on exit;
an unregistered reader seq-cst-increments/decrements `flat_foreign_active`
(`src/server.c:1119-1162`). Such a reader can therefore enter during `COPYING` and still acquire-load
the old current table; after the release swap, deferred table retirement keeps that old table
allocated until all published read regions are out (`src/kvstore.c:78-85`,
`src/server.c:9147-9178`, `src/server.c:9431-9444`).

The watchdog acts only when acquire loads see both `flat_resize_active` and state `QUIESCING`, and the
acquire-loaded arm time is more than 2,000,000 microseconds old. A successful shared abort increments
`flat_rz_watchdog_aborts` relaxed (`src/server.c:9272`, `src/server.c:9312-9322`).

### `COPYING`: rebuild, publish, retire

Each coordinator pass asks `flatTableCopyChunk()` to scan at most `1 << 16` old slots and returns if
more remain (`src/server.c:9273`, `src/server.c:9431-9433`). On completion, it relaxed-counts an
urgent service when the old request is still at least `URGENT`, relaxed-clears the replacement's
request, and release-publishes the replacement through `kvstoreFlatSwap()`
(`src/server.c:9434-9442`, `src/kvstore.c:84-85`). It then queues the old table for deferred
retirement, seq-cst-clears `flat_resize_active`, release-clears `mig_arm_lock`, clears the working
pointers, and seq-cst-assigns state `IDLE` (`src/server.c:9441-9447`).

The old table is not freed at the swap. `flatRetiredTablesTryFree()` returns while any foreign region
is active, any IO epoch is odd, or any worker is in a flat section; only when all checks pass does it
call `flatTableFree()` for every queued table (`src/server.c:9147-9178`). `flatTableFree()` drains
retirement records and frees the slots/table but does not decrement live values, which have been
copied into the replacement (`src/flatstore.c:96-107`, `src/flatstore.c:123-128`,
`src/flatstore.c:323-335`).

## Enforced invariants and caller preconditions

The implementation itself enforces these properties:

- Table sizes returned by `flatTableNew()` are powers of two, at least 1,024, and no smaller than the
  requested size; `mask` is exactly `size - 1` (`src/flatstore.c:71-77`).
- Exact zero is the only probe stop, so deleting to nonzero `FLAT_TOMB` preserves lookup reachability
  for keys later in the probe cluster (`src/flatstore.h:47-54`, `src/flatstore.c:210-219`).
- Insert publication is one CAS of the complete tag/pointer slot word; overwrite and delete each use
  one release store for their slot-word transition (`src/flatstore.c:247-252`,
  `src/flatstore.c:269-285`). Counter and resize-request atomics are additional operations after that
  slot transition (`src/flatstore.c:252-256`, `src/flatstore.c:286-292`).
- A resize request only rises on an existing table, urgent work is selected before normal work, and
  the replacement starts with request level `NONE` (`src/flatstore.c:88-94`,
  `src/server.c:9342-9357`, `src/server.c:9434-9436`).
- The table pointer is acquired by readers and release-published by swap; the replaced table is freed
  only after the region/section checks all pass (`src/kvstore.c:78-85`,
  `src/server.c:9166-9178`).

These are caller preconditions, not checks consistently enforced by the core functions:

- `flatInsert()` asserts only that the supplied pointer has no high bits; it does not reject null and
  does not range-check `hint_slot` before indexing `slots[hint_slot]`
  (`src/flatstore.c:239-247`). A null pointer can therefore produce a pointerless word while the
  success path still increments `used` (`src/flatstore.c:244-255`).
- `flatFindForWrite()` assumes non-null `t` and `slot` pointers; unlike `flatGet()`, it has no null
  guard before dereferencing them (`src/flatstore.c:207-209`, `src/flatstore.c:223-228`).
- `flatOverwrite()` does not verify that the slot is live, belongs to the same key, or contains a
  low-48-bit pointer-compatible replacement; it masks the replacement and preserves whatever high
  bits were already present (`src/flatstore.c:269-275`).
- `flatDelete()` does not verify a live slot and updates the counters unconditionally. Calling it
  twice for the same slot can return null on the later call while still decrementing `used` and
  incrementing `tombs` again (`src/flatstore.c:278-293`).
- `flatTableCopyChunk()` does not make the old table immutable; the coordinator's active flag and
  participant drain must establish that condition before copying begins
  (`src/flatstore.c:323-338`, `src/server.c:9379-9433`).
- The new-item kvstore adapter ignores the result of its fallback `flatFindForWrite()` and always
  calls `flatInsert()`, whose insert loop does not compare keys; callers must invoke this route only
  for an absent key. Passing the found key's live link does not make it safe because insert skips that
  live slot and continues probing (`src/kvstore.c:1102-1109`, `src/flatstore.c:239-267`).

## Code/comment discrepancies

The executable behavior above differs from several adjacent comments:

- The sizing comment says the target is at most one-third live, says “double (or more),” says never to
  shrink below the old size, and refers to a 0.5 trigger. The code instead uses a 35% grow boundary,
  grows by exactly one doubling, can halve repeatedly, and receives ordinary insert requests at 70%
  `used + tombs` (`src/flatstore.c:296-310`, `src/flatstore.c:301-317`,
  `src/flatstore.c:252-256`, `src/flatstore.h:40`).
- The header introduction says the low-14-bit ownership bucket survives as a per-slot tag, but the
  stored tag is the high 15 hash bits, and bucket-aware range operations recompute the low 14 bits
  from the key (`src/flatstore.h:1-9`, `src/flatstore.h:47-52`,
  `src/flatstore.c:341-346`).
- The `flatFindForWrite()` declaration says it remembers the first tomb, but the executable predicate
  remembers any nonzero word with no pointer bits; `flatInsert()` likewise reuses any non-live word
  and decrements `tombs` for every reused nonzero word (`src/flatstore.h:131-133`,
  `src/flatstore.c:227-230`, `src/flatstore.c:247-254`).
- The `flatTable.slots` field comment says 64-byte-aligned, but `flatTableNew()` requests ordinary
  `zcalloc()` and performs no explicit aligned allocation (`src/flatstore.h:106-108`,
  `src/flatstore.c:74-75`, `src/zmalloc.c:319-346`, `src/zmalloc.c:373-378`). The allocation
  comment's `ctrl`/`kv` terminology is also stale because
  the current slot contains only `w` (`src/flatstore.c:75`, `src/flatstore.h:56-58`).
- The file-level delete protocol says async preclear was removed, while the function/header still
  discuss an already or asynchronously cleared slot returning null. In every case, the executable
  path decrements `used` and increments `tombs` without testing whether the loaded word was live
  (`src/flatstore.c:10-12`, `src/flatstore.h:144-146`, `src/flatstore.c:279-287`).
- The API comment describes `FLAT_INSERT_FULL` after a complete probe, but a failed CAS that returns a
  non-live `expect` retries the same slot while consuming one of the fixed `size` loop iterations;
  under such races, the bound does not guarantee that every distinct slot was visited
  (`src/flatstore.h:137-140`, `src/flatstore.c:246-266`).
- The file-level protocol says each operation is one atomic access, but the implementation performs
  one atomic slot transition plus separate slot loads, counter RMWs, and possibly resize-request
  atomics (`src/flatstore.c:4-10`, `src/flatstore.c:246-256`, `src/flatstore.c:269-292`).
- The coordinator overview says completion swaps and frees the old table, and a later quiescence
  comment likewise refers to a direct `flatTableFree()` below. The completion path instead calls
  `flatTableRetire()`, and a later all-readers-out pass performs the free
  (`src/server.c:9237-9247`, `src/server.c:9383-9387`, `src/server.c:9441-9442`,
  `src/server.c:9166-9178`).
- `flatTableDiscardRetires()` says resize calls it with all workers parked. In the resize path it is
  reached from deferred `flatTableFree()` after the all-readers-out scan; by then
  `flat_resize_active` has already been cleared and workers can be using the replacement table
  (`src/flatstore.c:96-107`, `src/server.c:9166-9178`, `src/server.c:9441-9444`).
- The `flatRetire()` comment says an owning worker pushes onto the table stack and main closes and
  reclaims it. With a non-null worker-local sink, executable code instead prepends without atomics to
  that worker's list; only a null sink uses the table's release-CAS stack
  (`src/flatstore.c:130-132`, `src/flatstore.c:168-185`).
- A coordinator comment calls `flat_rz_state` a main-thread-owned integer read racily, but it is
  declared `_Atomic`, and `flatResizeState()` uses an explicit relaxed atomic load
  (`src/server.c:9250-9259`, `src/server.c:9275-9282`).

## File and line map

| Area | Authoritative implementation |
|---|---|
| Constants, slot encoding, states, and core structure fields | `src/flatstore.h:33-117` |
| Allocation and monotonic resize requests | `src/flatstore.c:71-94` |
| Key decoding and read/write probe algorithms | `src/flatstore.c:199-294` |
| Grow/same-size/shrink selection and chunked copy | `src/flatstore.c:296-339` |
| Flat kvstore flag and public adapter surface | `src/kvstore.h:86-108` |
| Kvstore's table field, acquire/release publication, and link conversion | `src/kvstore.c:39-85` |
| Flat table creation inside `kvstoreCreate()` | `src/kvstore.c:321-359` |
| Generic find/link/set routing into FLATSTORE | `src/kvstore.c:1025-1129` |
| Flat delete adapters and value-retirement handoff | `src/kvstore.c:1162-1199`, `src/db.c:1112-1130` |
| Full-insert wait, owner-lock handoff, retry cap, and stale-link reload | `src/db.c:504-557` |
| Physical node-database flag selection | `src/server.c:5561-5585` |
| Retire-stack push and ordinary payload destruction | `src/flatstore.c:168-188`, `src/flatstore.c:43-51`, `src/server.c:9016-9104` |
| Old-table deferred retirement and reader drain | `src/server.c:9147-9178` |
| Resize states, abort/watchdog, pending scan, and coordinator | `src/server.c:9235-9449` |
| Wait helper that drives the coordinator or watchdog | `src/server.c:15499-15522` |
| Worker resize-exclusion handshake | `src/server.c:21819-21842`, `src/server.c:22361-22364` |

## Mechanisms

- [FLATSTORE hash and tag encoding](mechanisms/algorithms/flat-hash-and-tag.md)
- [FLATSTORE probing](mechanisms/algorithms/flat-probe.md)
- [FLATSTORE load factor and resize](mechanisms/algorithms/flat-load-factor-and-resize.md)
- [Key-to-worker hash](mechanisms/algorithms/key-to-worker-hash.md)
- [Version bag](mechanisms/buffers/version-bag.md)
