# w-storettl design: retained TTL slots, exact reap, and eviction sidecars

Base: `b5b4d397d`.  This lane changes only storage expiry/eviction.  It does not change command
syntax, reply bytes, persistence formats, ownership, or reader synchronization.

## Laws and layout

- A shard owner is the only writer of every new index, wheel, and metadata byte.
- Published `KvObj` and table-pointer replacement remains immutable when read-local is armed;
  retirement remains QSBR.  No reader retry, lock, or new sequence is introduced.
- The unaligned in-object deadline is changed in place only while read-local is unarmed.
- Disabled selectors and `maxmemory=0` allocate nothing and add no object/sidecar access to the
  ordinary non-TTL GET/SET path.
- The fixed layouts remain `Op=336`, `Client=1984`, `ThreadCtx=1408`, `Shard=1440`,
  `FlatStore=944`, `Rob<64>=192`, `AtomicEntry=144`, and `Config=624`.
- Experimental choices are compile-time selectors, not new numeric knobs.  Existing numeric
  configuration retains its `0=off` meaning.

The feature implementations live in one dedicated header apiece, with only integration hooks in
the existing owner, executor, and INFO files:

- `store_ttl.h`: TTL selector and retained-slot helpers;
- `expire_wheel.h`: key-level hierarchical timing wheel;
- `eviction_sidecar.h`: maxmemory-only slot metadata.

## I-4: retained deadline slot

`KvObjFlags::HasTtl` becomes a physical statement: the allocation has the eight-byte deadline
slot.  Logical volatility is `slot && deadline >= 0`; `-1` in an existing slot means PERSISTED.
Keeping physical and logical state distinct is necessary because the bit participates in every key
and value offset.

For an unarmed store, PERSIST writes `-1` into the existing slot and removes the active-index
entry.  A later EXPIRE writes its deadline back into that same slot.  Both avoid re-headering,
value copying, allocation, retirement, and a second table publication.  For an armed store both
operations construct an immutable replacement; the replacement retains the slot, and the old
object is retired through the existing QSBR path.  TTL-preserving representation changes carry a
`reserve_slot` bit as well as the logical deadline so `PERSIST; INCR` and collection rebuilds do
not accidentally discard the reservation.  A plain SET without KEEPTTL is a new value lifetime
and may discard it; deletion and reload likewise end the in-memory lifetime.

All expiry predicates must test `deadline >= 0` before `deadline <= now`.  The non-TTL path keeps
its existing flags-first branch and does not read the clock or deadline.  Expire-index insertion is
based on logical volatility, not slot presence.

### Deadline-sidecar prototype

`TOMO_TTL_DEADLINE_SIDECAR`, default `0`, adds a deadline payload to the key `ExpireIndex` and makes
owner TTL probes read that payload after the object flag test.  Non-TTL objects do not probe it.
The prototype intentionally retains the in-object deadline as an immutable-version fallback and
transport field.  Removing those bytes in this tree is not a local header edit: constructors hand
around bare `KvObj*`, MVCC parks old objects in layout-locked `AtomicEntry`, snapshot capture can
retain an older object, and foreign readers may hold a captured old object.  A single hash entry
would let an old object consume a newer object's deadline.

Thus this selector measures the proposed extra hash/cache probe and validates index maintenance;
it does not claim the eight-byte saving.  A production removal would require a `(hash, KvObj*)`
versioned deadline store, QSBR retirement of its cells, and an object-plus-deadline carrier through
every constructor/install path.  At 70% load a minimally exact 16-byte cell costs about 22.9 bytes
per live TTL versus the current eight inline bytes plus the existing hash/state index, so the
prototype must show an allocator/cache win before that wider contract is pursued.  This is also why
narrower deadline encodings are deferred: retained slots already eliminate the hot copy, while the
candidate sidecar does not currently leave bytes to spend.

## I-7: hierarchical timing-wheel selector

`TOMO_EXPIRE_WHEEL`, default `0`, selects a per-`FlatStore` key-expiry wheel; `0` retains the sampler
for a clean A/B.  Hash-field TTL attention remains on its current sampler because one hash object
can contain many independent field deadlines.

The wheel has 11 levels of 64 buckets at one-millisecond base resolution.  Six bits per level cover
all positive signed 64-bit millisecond deltas.  A nullable heap state contains the bucket heads,
non-empty scheduling state, and intrusive nodes keyed by `(hash, KvObj*)`.  It is allocated by the
first logical TTL and released with the last, so a shard with zero volatile keys owns no wheel
allocation.  Rehashing moves slot words but not nodes because object identity is stable.

Schedule, reschedule, cancel, cascade, and due-pop are owner-only.  Cascaded nodes count against the
same bounded cycle budget as reaped nodes, preventing one clustered upper bucket from becoming an
unbounded owner stall.  A due node is detached before the callback; stale entries are consumed,
and an object protected by an undecided atomic record is requeued instead of dropped or left at a
busy-spinning head.  Snapshot suppression and the existing notification -> AOF delete -> erase
order remain unchanged.  Volatile eviction continues to use the existing active index for bounded
random candidates.

The split executor currently samples only in its idle sweep, so a wheel there would still starve
under continuous work.  Wheel builds therefore perform a bounded, millisecond-gated due pass from
the busy batch loop as well.  Sampler builds retain their exact scheduling path.  An empty wheel is
checked through its null state before walking shards, keeping the no-TTL command cell free of wheel
work.

INFO adds `active_expire_reap_lag_ms_max`: the saturating maximum of `now - deadline` observed on a
successful active reap.  It is updated only on the cold reap path, published in existing alignment
holes, and aggregated as a maximum.  Comparing it with `expired_keys` and a known elapsed test
population measures sampler backlog without maintaining a shadow ordered structure that would
contaminate the A/B.  CONFIG RESETSTAT baselines the counter like other cumulative statistics.

## I-8: maxmemory-only eviction metadata

An `EvictionSidecar*` replaces the existing eight-byte eviction sampling cursor in `FlatStore`; the
cursor moves into the heap object.  The sidecar owns one byte array parallel to each live table and
one for a prepared snapshot table.  It is allocated only on `maxmemory: 0 -> nonzero`, freed on the
reverse edge, and counted in the resident migration estimate but not in the stable logical
maxmemory budget.  At the 70% table target the physical cost is about 1.43 bytes per live key.

Metadata belongs to a physical slot, not a value object.  New slots initialize it, same-slot
replacement preserves it, erase/tomb creation clears it, and rehash carries it with the slot word.
Snapshot preimage marks retain it because `kTombBit | pointer` is not an empty slot.  Direct atomic
capacity/exchange paths mirror the same transitions.  Pending-only MVCC versions have no byte and
receive fresh metadata only if they become physical, preserving `AtomicEntry=144`.

Owner lookup/touch and victim scoring use the sidecar byte.  Foreign readers never load or publish
the sidecar, so owner touches no longer dirty the object header line they acquire.  The executor's
cached LRU clock uses all eight bits; its resolution remains the boot-latched
`1 << lru_clock_shift` seconds and its alias horizon self-derives as
`256 << lru_clock_shift`.  LFU remains capped at 31 so this item does not change its probability or
decay model.  No knob is added.

Sidecar/table allocation is transactional.  If first-arm allocation fails, maxmemory remains
enabled and fails closed to no victim/OOM rather than silently exceeding its limit; a later live
configuration refresh may retry.  Disabling maxmemory releases every metadata array.

## Expected effect, risks, and measurement

- I-4 removes allocation/copy/retire work from unarmed PERSIST and from EXPIRE after PERSIST.  Risk:
  confusing slot presence with a live TTL, or failing to carry slot history through a preserving
  rewrite.  Measure `expireindex.py` at one shard, `expwide.py`, `edgetime.py`, notify, s6/differ,
  and allocation/instruction counts for PERSIST -> EXPIRE loops.
- I-7 replaces empty-slot sampling with bounded work proportional to scheduled/cascaded keys and
  should sharply reduce expiry lag under large simultaneous populations.  Risks are clustered
  cascade debt, wall-clock jumps, missed cancellation, and atomic deferral.  Compare selector 0/1
  using the expire batteries plus `expired_keys` and `active_expire_reap_lag_ms_max`.
- I-8 extends the LRU window eightfold and moves owner touch writes off the acquired object line.
  Risks are a missed topology mirror and enabled-mode cache cost.  Run all `evict_battery.py`
  sections, OBJECT IDLETIME/FREQ, notify, snapshot/atomic eviction cases, and armed foreign-reader
  traffic.
- For every commit compare GET/SET instructions per operation on non-TTL keys with
  `maxmemory=0`.  The required result is null: no sidecar allocation or access and no new clock read.

