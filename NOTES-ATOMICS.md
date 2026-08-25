# Opt-in epoch-MVCC atomics

`--atomic 1` makes `MSET`, `MSETNX`, multi-key `DEL`, and `UNLINK` atomic across shards. `MGET`,
`EXISTS`, and `TOUCH` read one committed snapshot. The default is `--atomic 0`; a shard whose
side-map pointer is null follows the original store path, allocates nothing, and pays one predicted
branch at dispatch. A single atomic activity word combines the enabled bit with in-flight-group and
live-record references, so OFF/draining selection needs one acquire load. `--atomic-window`
defaults to 256 in-flight atomic write groups; zero means unlimited. Both knobs are numeric and
live through `CONFIG SET/GET`.

## Representation and publication

`KvObj` is unchanged. Each shard lazily creates an owner-only hash-to-chain side-map on the first
atomic validate that reaches it. A version node contains a `KvObj*` (null is a tombstone), the
`ScatterState*` group and pointers to its epoch/reference fields, or a direct epoch for a plain
single-key write. The initial node records the value before the first tracked install and has epoch
zero, which is the always-committed predecessor.

Atomic writes use the existing two hops:

1. Validate creates every key record and owner-links an invisible prepared node, builds and
   accounts every replacement object, performs cumulative maxmemory admission and table-capacity
   reservation, captures `MSETNX`'s existence decision, and crosses the snapshot pre-image gate.
   Failure here installs nothing. The last validator release-marks an aborted group; owner cleanup
   ignores and reclaims its prepared nodes. IO threads never mutate the owner-only map.
2. Apply only detaches/attaches already-owned pointers and turns prepared nodes into physical
   candidates. It is infallible.
   Owners may finish in any order. The last completer draws `T = ++commit_seq` and publishes
   `group->epoch.store(T, release)`.

There is no abort after apply starts, rollback, ordering wait, publish frontier, or group lock.
Different atomic groups execute concurrently even when every key overlaps.

## Visibility and the inversion invariant

A tracked read selects the candidate with the largest nonzero committed epoch at or below its
snapshot. The predecessor's epoch zero is eligible. Multi-key readers capture `commit_seq` once at
dispatch; single-key readers capture it immediately before execution. Candidates newer than the
cut and uncommitted candidates are skipped without waiting.

The chain is **not sorted**. G1 may physically install before G2 on one owner while G2 installs
before G1 on another, and their final tickets are drawn in yet another order. The physically live
table may therefore be a mix. Both resolution and promotion scan the complete chain and compute an
epoch argmax; neither follows link order or assumes that the physical node wins.

An ordinary one-key write that encounters a record deep-clones the committed candidate, installs
the clone as a new version, and draws its own ticket before invoking the existing handler. That
lets collection handlers retain their in-place mutation model without changing a predecessor that
an older snapshot can still select. Replacement and erase calls update that same version node.

## Lifetime and promotion

Each IO thread publishes the minimum snapshot of its active scatter groups, or `UINT64_MAX` when it
has none. The server floor is the minimum of those publications. This is the freeing invariant:

> A version is freed only after every version in its key record is committed and has an epoch
> strictly below the global floor. Consequently every active reader that could select a removed
> predecessor has retired; the promoted argmax winner is the answer for every remaining reader.

Snapshot registration publishes its initial cut and then confirms `commit_seq`. Cleanup loads a
commit cutoff before it loads the floor and refuses to promote any version newer than that cutoff.
Those operations are sequentially consistent: cleanup that missed a new floor publication is
ordered before it, so its earlier cutoff cannot include a later commit that the reader confirmation
missed. This closes the publication/reclamation race without making resolution wait.

Promotion runs only on the shard owner. Atomic group retirement posts cleanup tasks to its touched
shards, and the next owner touch also attempts the key. A bounded owner sweep chooses the largest
ticket, installs that exact winner (or erases for a tombstone), retires borrowed losers through the
existing borrow registry, removes the record, and increments the free counters. `ScatterState`
arenas whose epochs are still named by nodes stay in their owning IO pool's deferred list until the
last node drops its reference.

Turning atomic mode off affects only newly admitted commands. Already admitted groups commit,
single- and multi-key reads keep consulting any surviving side-map, and cleanup deletes the map
only after its last record is promoted.

## Admission and progress

Admission reserves one window slot before allocating the scatter arena. At the cap, prepare returns
backpressure without consuming the RESP frame. The connection parse barrier holds younger commands,
while the IO active set continues to parse and retire other connections. Group retirement releases
the slot. Resolution never waits; cleanup is bounded and deferrable.

`INFO STATS` exposes `atomic_groups`, `atomic_inflight`, `atomic_predecessor_reads`,
`atomic_chain_max`, `atomic_promotions`, `atomic_window_stalls`, and `atomic_records_freed`.
`tests/atomic_torn.py` requires predecessor reads and promotions to advance so an all-zero,
mechanism-never-fired run cannot pass.

## Deferred commands

This lane intentionally leaves movers and store-producing commands non-atomic: `RENAME`,
`RENAMENX`, `COPY`, `SMOVE`, `LMOVE`, `RPOPLPUSH`, `SINTERSTORE`, `SUNIONSTORE`, `SDIFFSTORE`,
`BITOP`, `PFMERGE`, `LMPOP`, `ZMPOP`, `ZRANGESTORE`, and `SORT STORE`. They still resolve recorded
inputs and stamp writes to recorded destination keys, but their multi-key effect retains the prior
command semantics. `KEYS`, `SCAN`, random-key selection, expiry, eviction, and whole-database flush
are likewise not promoted into snapshot-atomic operations by this lane. FLUSH installs one ticketed
tombstone cut per owner before clearing plain table entries, which preserves predecessor lifetime
and progress under continuous atomic traffic without claiming a cross-owner atomic FLUSH.
