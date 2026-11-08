# FlatStore decisions retained by readability-a8

Recorded 2026-11-08 from lane base `7595a6705`; source behaviour is frozen.
Dates below are archival dates unless an earlier incident date is explicitly given.
Historical numbers are transcribed from the old comments, not reproduced measurements
or new performance claims. Code comments state the present mechanism and its hazards.

## 2026-11-08 — Per-shard ownership and read-local publication

`FlatStore`, `insert_read_local`, `read_local_prefetch_capture`: the old overview
contrasted the abandoned per-node fork with per-shard ownership and claimed that no
atomics or epoch reclamation remained. That no longer describes this code. Ordinary
owner access and armed foreign access have different publication/lifetime rules.
Resizing moves slot words, but replacement can allocate/copy a new object; “a key is
allocated once” and “KvObj is never copied” are not valid global invariants. Shard
migration also rebinds the retirement sink (`Server::adopt_read_local_retire_sink` and
`ExLoopT`'s `rebind_owned_shards`), not just router bits.

## 2026-11-08 — Incremental resize and completion reservation

`rehash_step`, `rehash_step_read_local`, `prepare_resize_retirement`: retain bounded
slot migration and reserve the armed completion record before publication. The old
fork anecdote reported a 2.4 s p99.99 reduced to 39 ms by serve-while-copy. It motivates
avoiding a capacity-sized owner pause but is not evidence about this release.
Destination publication precedes old-slot tombstoning during rehash; replacement
removes the old-table copy first. Thus uniqueness is a lookup/publication invariant,
not a claim that two physical words can never briefly name the same object.

## 2026-11-08 — Decouple router and slot-index bits

`slot_start`, `hash_key_mix`: routing fixes low hash bits for keys assigned to a shard;
mix again for table homes. The removed comment reported about 6,600 probes per lookup
and a 2.5–2.7x improvement from remixing. Those numbers belong to the old experiment;
the present code retains the mixing operation and full key equality.

## 2026-11-08 — Expiry-index migration and empty collapse

`ExpireIndex::insert`, `sample`, `collapse_empty`: incremental movement avoids placing
a million-deadline migration inside one SET (the old comment described tens of
milliseconds of owner stall). A zero population releases large/migrating buffers;
minimum-capacity storage clears 16 state bytes. The former monotone-capacity clear
made every later live-to-zero transition pay for a historical burst. The old comment
claimed the destination was at most about 41% loaded at normal migration completion;
that estimate is not used to promise the backstop is unreachable. `finish_migration`
can drain the rest, so the contract explicitly distinguishes that path.

## 2026-11-08 — Tombstones preserve expiry-index lookup

`ExpireIndex::migrate`, `erase_in`: moved slots remain tombstones because erase still
probes the source table. The removed incident description associated premature EMPTY
slots with INFO expires over-reporting after PERSIST. The concrete probe-chain and
counter invariant remains beside the code.

## 2026-11-08 — Hash selection and fixed calling shape

`hash_key`, `siphash12`, `ExpireIndex::insert`: keep keyed startup hashing and the
existing enum branch; the previous “small measured per-op cost” for SipHash was not
quantified. Keep `insert`'s unused deadline parameter and call shape: the old comment
records an inlining-layout reason, and this lane does not change signatures.

## 2026-11-08 — Snapshot reservation follows population

`snapshot_prepare`, `insert`: reserve at least the current capacity and at most twice
it, with the live-set estimate controlling excess headroom. Repeatedly doubling the
current table at every snapshot grows an idle store without population growth.
Prepared-table and capture admission retain enough terminating-empty capacity for the
post-capture merge, including tombstones. A snapshot's lifetime is not proven to have
a fixed wall-clock bound, so the old “short and bounded” claim is removed.

## 2026-11-08 — Same-length overwrite accounting

`try_overwrite`: equal lengths imply zero footprint delta, so skip two size computations.
The removed comment attributed 7.7% of a historical SET cell's cycles to `kvobj_size`.
The armed path still refuses in-place overwrite; this decision does not relax it.

## 2026-11-08 — Armed write allocation and refusal

`make_set_string`, `discard_set_value`, `refuse_over_budget`, `read_local_cache_put`:
use post-grace inline-string blocks, fall back to allocation, and release cache memory
on allocation/admission refusal or FLUSH. An unpublished failed replacement needs no
grace period. The cache belongs to the owner and can contain sibling-shard blocks;
its sink is rebound at a quiesced handoff, not immutable for the process lifetime.
Successful eviction does not repeatedly discard the cache. The old release-all comment
incorrectly said it preceded eviction and described all callers as whole-server events.

## 2026-11-08 — Object-idle allocation failure is local

`configure_object_idle`: the old SO5.1 decision retains partial-clock cleanup and a null
slot on allocation/population failure. OBJECT IDLETIME then reports zero for the store;
eviction still reads its five-bit metadata. `configure_maxmemory` applies the requested
limit/policy even when clock creation fails.

## 2026-11-08 — Accounting scans do not expire keys

`scan`, `scan_visit`: LB's bucket-byte census passes `expire_on_visit=false` because it
runs outside a logical operation's pinned cut. The removed incident says the expwide
battery caught physical expiry between MGET fan-out fragments when census became the
default. SCAN's `kExpiresVisited` exception deliberately permits retirement waiting;
other expiry walkers keep the availability guard. A home visit can traverse a long
probe chain; COUNT/10*COUNT are checked between visits, not inside a home.

## 2026-11-08 — Expiry registration follows logical deadlines

`track_expire`, `find_hash_in`, `atomic_exchange_physical_read_local`: keep the empty-index
fast return but erase a tracked hash when SET clears its TTL. A retained physical TTL
slot with deadline -1 is not logical volatility. INFO's exact index count cannot tolerate
the stale entries that active reaping could eventually clean. The old comments also
named a sidecar prototype; no such prototype is added or relied upon here.

## 2026-11-08 — Borrow lookup index is optional

`borrow_find`, `borrow_index_added`, `borrow_index_rebuild`: the vector is authoritative;
index failure falls back to scanning. The old comment reported borrowed GET increasing
from 2,903 to 3,185 ns/op as outstanding borrows went from zero to about 1,100, while a
non-borrowed control stayed near 1,100 ns. Keep the threshold of 32 entries and the
failure fallback; no new comparison or threshold tuning is performed.

## 2026-11-08 — Field expiry needs an unfiltered hash probe

`find_any_hash_in`: unlike `find_hash_in`, field attention cannot require a key-level
TTL. The old incident reported `hash_field_expires` falling to zero because the wrong
probe made the cycle deregister each hash. The distinct predicate remains documented.

## 2026-11-08 — Call-based key comparison in register-heavy loops

`insert_into`, `insert_into_read_local`, `read_local_capture_in`: retain `key_mem_eq`.
The insertion comment reported 13 extra spill instructions on first insert with inline
comparison, while full comparison usually runs only after a 15-bit tag match.
For the armed capture loop, the archived 9M-operation instruction-slope comparison used
`--shards 64 --thread-mode 1s --read-local 1 --atomic 1`, two threads:

| Key bytes | `key_eq` instr/op | `memcmp` instr/op | Difference |
|---|---:|---:|---:|
| 16 | 1789.7 | 1764.2 | -25.5 |
| 24 | 1814.1 | 1783.2 | -30.9 |
| 40 | 1848.3 | 1813.1 | -35.2 |

The unarmed tuning workload did not enter capture. These are archived instruction counts,
not a throughput verdict; both helpers retain exact byte equality.

## 2026-11-08 — Read-mostly topology and owner counters

`FlatStoreLayoutLock`, `read_local_state_acquire`: keep offset-based separation on both
sides of the reader range. The removed narrative described tab_ at +208 and live_ at
+240 sharing a line; atomic_pending_ at +8 collided with scratch vector controls at
+16/+40/+64. It also described a latent atomic_version_bytes_ +0 collision hidden by
store_offset 56 and a 64-byte-aligned shard, with three of four possible 16-byte base
alignments exposing it. These are historical offsets, not the current layout.

The 28-byte gap keeps sizeof(FlatStore) at 944 rather than the old hypothetical 916.
It now contains a storesize pointer at bytes 4..11 and a constructed atomic idle-clock
pointer at 12..19. The static assertions constrain named endpoints; they do not prove
all nearby fields are read-mostly (`field_ttl_gate_` changes during key work), nor that a
sub-64-byte range fits a cache line for every base address. No layout token is changed.

## 2026-11-08 — Cold fields stay after hot state

`FlatStore` field tail, `field_expires_`: the removed comment records an instruction-count
regression when cold state enlarged offsets of clocks, maxmemory and snapshot fields.
No quantitative result was attached. Preserve the layout and lazy allocation; the
field index can be registered by imported images as well as native HEXPIRE handlers.

## 2026-11-08 — Collection size accounting bracket

`ObjectSizeTracker::finish`, `cancel`, `note_object_size_change`: retain delta accounting
and finish-before-delete lifetime rules. The old comment dates an accounting underflow
incident to 2026-08-25. No missing bracket is fixed in this lane; the contract makes the
borrowed object's required lifetime explicit.

## 2026-11-08 — Shutdown releases abandoned script PINs

`atomic_release_abandoned_script_pins`: the XS-SHUT-1 decision releases kind-0 PIN prefix
nodes after workers join and before pending-record shutdown checks. A stop between PIN
and UNPIN/APPLY can abandon an unacknowledged activation; no later owner wave will drop
those references. Post-join IO teardown is the production caller.

## 2026-11-08 — Script PINs force version admission

`atomic_needs_version`: testing pending value records alone misses a competing write on
an intent-only key. APPLY validation needs the resulting epoch. The shared predicate
includes script intents and remains the admission decision point.

## 2026-11-08 — Validate newer-ticket read-modify-write conflicts too

`atomic_script_changed`: do not cap conflicts by the activation's reserved ticket.
A writer with a newer ticket may have read the pre-activation value before the activation
installs. The old “at most one retry / cannot livelock” assertion is not established by
this predicate under continued competing writes; the new comment does not promise it.

## 2026-11-08 — Clamp and expose accounting underflow

`atomic_gauge_sub`, `atomic_resolve_internal`: the old comment records eleven subtraction
sites and a delayed group-install abort after gauge wrap. Parked-predecessor mutation
was the cited resolver defect. Keep centralized clamp/count and the test expectation
that underflows stay zero, rather than claiming the accounting guard repairs visibility.

## 2026-11-08 — Atomic reservation covers deletes and tombstones

`atomic_prepare_capacity`: reserve at the 70% load threshold, count tombstones, and advance
eight old slots per additional key plus one step. A delete pass also needs the trigger;
a value-writes-only reservation path leaves detach tombstones accumulating toward full.
Capacity failure can defer the pass; a successful reservation precedes physical install.

## 2026-11-08 — Logical clear restores read context

`atomic_tombstone_all`, `atomic_install_plain`: ordinary plain installation selects its
new clone for the next handler. FLUSH must save and restore both cut and origin instead.
The removed incident described later direct RENAME and MULTI pop reads missing a newer
acknowledged MSET because FLUSH's old cut was left installed with no connection context.

## 2026-11-08 — Repair ordering in both reads and cleanup

`atomic_resolve_internal`, `atomic_collapse_impl`: keep the adjacent same-connection epoch
repair before visibility/ranking. A wide group's final fragment can obtain its ticket
after a younger transaction. The old cleanup incident recorded 246/1120 reproductions.
The resolver's removed experiment narrative says collapse-only passed its stale-read
probe at 16 cores, then failed multires in 3/8 runs at the gate's eight-core geometry;
restoring resolver repair gave 0/8, at an approximately 2% atomic-path A/B cost.
These are archival results, not this lane's tests. Private epoch-zero overlays outrank
committed versions so repeated transaction writes do not mutate parked predecessors.

## 2026-11-08 — Tripwire observations are diagnostics

`atomic_resolve_internal`: the old #77/seed-19 narrative identified EXISTS overcount
geometry. Keep the arming gate, finite-cut predecessor check, unfiltered same-key walk,
and bounded 4096 ticket polls. Counters distinguish masked matches, visible losing
versions and undecided publication timing; an observation is not a correctness verdict.

## 2026-11-08 — Collapse keeps retained-suffix ordering and group lifetimes

`atomic_collapse_preserves_tickets`, `atomic_collapse_impl`: a collapsed winner becomes an
epoch-less base, so lower-ticket retained candidates for that key can invalidate cleanup.
Check the whole suffix before promotion. Filter closure precedes the last ScatterState
pin decrement because grouped hashes still come from it. ReadLocal template selection
retains the same QSBR path and inlining attributes; no work bound is inferred from the
small `atomic_sweep` budget argument.

## 2026-11-08 — Keep the eligible private interface split

`FlatStore`'s 60-definition suffix from `expire_found` through `rehash_step` moves into
`flatstore_impl.h`, immediately after the class. Anchored and lottery-read functions stay
at their paths, and preceding definitions stay before them. All moved body tokens retain
their order. The candidate compares IDENTICAL to frozen release `5c36312818`, so this
partial split is kept; no runtime redesign or translation-unit change is needed.
`expire_found` retains `noinline` and the in-class definition's implicit inline property on its
declaration. The out-of-class definition inherits both; repeating the attributes there
causes a GCC warning, even though the compared binary is unchanged.
