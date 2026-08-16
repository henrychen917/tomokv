# MVCC atomic multi-key commands

## Scope and guarantee

With `tomokv-atomic` enabled, eligible cross-shard whole-value writes install one invisible version
per key. Each install points to one shared `tomoCommit`. The owners publish their own stamped-index
links independently, and the last owner to decrement `tomoCommit::shards_remaining` assigns the
commit timestamp and release-stores it into that shared record.

That one release store is the visibility event for the entire group. A reader ignores a stamped
version while the shared marker is zero, so any number of owner-local publications can exist
without exposing a torn group. No owner waits for another owner: a non-last decrementer returns to
its normal slice immediately. There is no commit drainer, ready-group MPSC, elected producer,
reserved owner-operation ring, or per-key cross-core publish message.

An eligible cross-shard read samples the committed clock once at dispatch. Call the resulting
snapshot `T`. Normal resolution accepts a group version only when its shared `commit_ts` is nonzero
and at most `T`, then selects the greatest visible `(commit_ts, version_order)` for each key. Every
member of a write shares the same marker, which is why MGET cannot observe only a committed subset.

The installing connection has a narrow read-your-own-writes exception. A pipelined read whose
snapshot predates its own preceding write may select that connection's newest uncommitted physical
version, or its newest committed version above `T`. Other clients' post-snapshot commits remain
invisible. A later request/response read starts only after the write reply; reply publication
follows the commit marker and visible clock, so its snapshot includes the write.

The feature is modifiable and defaults to `no`. `tomokv-atomic-window=-1` derives admission from
writer concurrency and pipeline depth. `tomokv-atomic-reclaim-limit=-1` derives a process-wide
retained-version pool. Both controls park only new atomic writers; readers, admitted owners, and
retirement continue.

> Version-chain preservation and prune-after-grace are connected end to end only for FLAT
> kvstores. Atomic mode therefore requires FLAT storage.

## Default-OFF path

The admission block is nested under `server.tomo_atomic != 0`. With atomic mode off, commands do
not reserve the atomic window, load reclaim pressure, allocate a commit or owner array, sample the
MVCC clock, or enter owner-local publication.

The existing `exThread::atomic_publish_pending` word is a rename of the former atomic-only pending
word and does not move the worker layout. Owner-list heads are allocated lazily with the atomic
lifecycle tables instead of being appended to `exThread`, preserving the tuned worker-array stride
and off-mode allocation behavior. Retired client/group fields remain layout reserves.

Raw reads return before MVCC resolution. Existing version bags are still resolved if the setting is
changed while admitted groups remain in flight.

## Commit clock and marker

`commit_clock` is a cache-line-isolated `_Atomic uint64_t`. Its high bits hold the last fully
published timestamp and its low bit is a writer-only publication latch:

```text
2*T      timestamp T is fully published
2*T + 1  a last owner is publishing T+1; readers still use T
```

Readers acquire-load the word once and shift right; they never spin on the odd state. After the
last `shards_remaining` decrement has acquired every owner-local publish, that worker:

1. CASes the even clock word to its odd form;
2. release-stores `T+1` to the group's shared `commit_ts` marker;
3. release-stores `2*(T+1)` to the clock.

A reader sampling before step 3 uses old `T` and excludes the group. A reader sampling after step 3
acquires the prior owner publications and includes the group consistently. The clock latch
serializes only this constant-time two-store publication interval; it is not a shard rendezvous.

## Data structures

### Shared `tomoCommit`

| Field | Role |
| --- | --- |
| `_Atomic uint64_t commit_ts` | Zero until the last successful owner publishes the single group marker. |
| `_Atomic unsigned int refs` | One transient group reference plus version references, trimmed to the exact install count before deferred publication. |
| `_Atomic unsigned int shards_remaining` | Distinct owner records that have not completed local stamp/cancel publication. |
| `_Atomic size_t reclaim_bytes` | Owner-local byte totals, each folded once before its counter decrement. |
| `void *owner_records` | Commit-owned stable `csMsetOwner[]`; it outlives `csGroup` until all version references retire. |
| `csGroup *group` | Valid through marker/no-op completion, then cleared before the reply can retire the group. |

The reference count is pre-reserved before any version can publish its commit pointer. A terminal
key-dependent install decision trims it once to `1 + exact_installs`, before owner cancellation can
make metadata retire. Ordinary MSET/DEL install exactly their declared key count and need no trim.

### Owner record

There is one stable `csMsetOwner` per distinct install owner. The first allocation reserves at most
`min(expected_keys, num_workers)` records and never moves, including across NX retry waves. An
owner appends its installed versions to `head`/`tail` in install order, accumulates reclaim bytes,
and carries the record through these owner-private phases:

- `NEW`: installs may still append;
- `WAIT`: a strictly key-dependent group has not published its terminal decision;
- `PRUNE`: local stamps are published and the record waits only for the shared marker;
- `DONE`: retirement was armed or cancellation cleanup completed.

The owner-private list heads live in a lazy atomic-only array indexed by worker ID. Only that worker
mutates its element. The list is not a communication queue and has no capacity/backpressure path.

### Per-version metadata

Relevant `tomoVerMeta` fields include the shared `commit`, physical `version_prev`, unordered
`stamped_head`/`stamped_prev`, immutable connection identity and install order, owner/bucket
lifecycle identity, cancellation/retirement state, and `owner_next` for the local record chain.
The retired embedded STAMP/PRUNE carriers are gone.

`owner_ops_pending` remains a local lifetime guard: success uses `2 -> 1` when stamping and
`1 -> 0` when retirement is armed; cancellation uses `1 -> 0`. It no longer counts queued
cross-core operations.

## Install-to-publish protocol

### 1. Admission and registration

Atomic admission happens before fake-ring allocation. Registration marks the group uncommitted,
allocates its shared commit, reserves a connection-global install-order range, and
release-increments the real client's `mset_pending_count`.

Each owner install prepends an invisible whole-value version to the physical chain, acquires its
owner/bucket lifecycle reference, charges exact owner reclaim telemetry, attaches the shared
commit, and appends the version to that owner's stable record. Registration precedes every owner
queue publication.

### 2. Ordinary MSET and DEL publish inline

MSET and DEL are coalesced to one sub per distinct owner and their outcome is known before
execution. While holding its ordinary worker lock, an owner:

1. installs every key in its coalesced sub;
2. walks only its record and release-publishes each stamped-index link;
3. folds its local reclaim-byte total once;
4. places the record on its private post-marker retirement list.

After unlocking, it completes the normal group-pending decrement and then acquire-release
decrements `shards_remaining`. A non-last owner immediately continues unrelated work. The counter
RMW chain carries every local stamped-index release to the last owner, and the ordering after the
normal pending decrement also proves the group cannot be returned to IO while a sub is live.

### 3. Strictly key-dependent shapes

MSETNX, NX destinations, and read-then-write/two-hop shapes can discover success only after multiple
owner waves. Their owner record enters `WAIT`. `csMsetInstallDone` performs the terminal decision,
trims the pre-reserved references, initializes `shards_remaining`, and release-publishes
`INSTALL_READY`.

Each worker revisits at most the private-list population seen at slice entry. An unready record is
rotated once and the worker continues with normal work; it does not spin or drain to empty. Once
the terminal decision is acquired, that owner stamps its local chain or cancels it under its own
lock, folds bytes, and decrements the group counter. This deferred local revisit is used only where
the command is strictly key-dependent.

### 4. Last owner and reply

The owner whose counter decrement observes one is the last local publisher. On success it advances
the encoded clock and stores the shared marker. On cancellation it publishes no timestamp. It then
performs only O(1) group work:

1. publishes the group reclaim charge;
2. seals reshard lifecycle accounting;
3. release-stores `FINAL_READY`;
4. detaches the commit-owned owner array from `csGroup`;
5. release-decrements the client's pending count;
6. release-publishes the group-head CDB byte and posts the existing completion notifier;
7. drops the transient group reference.

There is no MPSC hop or elected completion thread. CDB publication is the first point at which the
origin IO thread may reassemble and free `csGroup`.

## Reader resolution and atomicity

The read-time visibility algorithm is unchanged by owner-local publication. Its important cases
are:

- raw values bypass MVCC state;
- a stamped version with `commit_ts == 0` is invisible and resolution falls through to its
  predecessor;
- a non-own version is visible only at `commit_ts <= T`;
- all versions in one group read the same marker;
- tombstones resolve as absence;
- the connection-identity branch provides only same-client RYOW widening.

Thus partial local publishes cannot tear MGET: before the marker every group member is invisible,
and after the marker the reader's clock acquire covers all stamped links. No read-side wait is
introduced.

## Retirement and backpressure

A successful record remains on its owner's private list after stamping. At the start of a worker
slice, `csOwnerPublishStep` freezes the currently published clock and arms retirement only for
records whose marker is nonzero and at most that frozen frontier. Markers created during the pass
remain for the next pass. This preserves nondecreasing eligibility timestamps for the existing O(1)
FLAT FIFO frontier caches without sorting.

`tomoArmVersionRetire` starts the existing marker-plus-snapshot-frontier QSBR path. A completed
grace removes only versions below the anchor's `(commit_ts, version_order)`. Physical free occurs
after a second grace, at which point the lifecycle reference, exact owner charge, and commit
reference are released. Detached predecessors remain pinned by `owner_ops_pending` until their
owner-local maintenance reaches them.

Each owner folds its byte total once into `tomoCommit::reclaim_bytes`; the last owner performs the
single global pool charge. The conservative charge remains until the final version metadata loses
its commit reference. `tomokv-atomic-reclaim-limit` continues to gate only new writers and remains
the memory-safety backstop.

## Memory-order summary

| Edge | Ordering and guarantee |
| --- | --- |
| Install metadata / local chain | Owner lock plus release attachment of the shared commit pointer. |
| Local stamped index | Owner release publication; reader acquire traversal. |
| All owners to last owner | Acquire-release `shards_remaining` RMW modification-order chain. |
| Group visibility | One release store to shared `commit_ts`; readers acquire it through resolution/clock ordering. |
| Snapshot cut | Final commit-clock release; reader's single acquire sample. |
| Terminal decision | `INSTALL_READY` release; key-dependent owners acquire before stamp/cancel. |
| Reply | CDB release and notifier post after marker/no-op completion and lifecycle sealing. |
| Retirement | Marker at or below frozen frontier plus QSBR grace, using existing O(1) cached frontiers. |

## Core invariants

1. Registration and commit allocation precede every version install publication.
2. Only an install owner mutates that owner's version chains.
3. Every owner publishes only its local versions and then decrements once.
4. A non-last owner never waits for another shard and immediately resumes normal work.
5. `commit_ts` stays zero until the counter chain has acquired every local publish.
6. The single marker release makes every group member visible together.
7. Readers never wait; marker zero selects the predecessor and marker above `T` is excluded.
8. Reply publication follows the marker and visible-clock release, preserving next-read RYOW.
9. Retirement starts only after the marker and completes only after QSBR grace.
10. Reassembly remains the exactly-once atomic-admission retirement point.
11. OFF mode enters none of the atomic allocation, publication, snapshot, or completion machinery.

## Implementation map

| Area | Files/functions |
| --- | --- |
| Clock, owner records/lists, counter completion, reply wake | `src/server.c` |
| Shared commit and version metadata | `src/object.h` |
| Group/client/worker layouts | `src/server.h` |
| Version install, stamp, cancel, resolve, prune, promotion | `src/db.c` |
| FLAT retirement and cached grace frontiers | `src/flatstore.c`, `src/server.c` |
| Admission knobs and live apply | `src/config.c` |

See [owner-local publish](mechanisms/communication/owner-local-publish.md) and
[commit-time timestamp ordering](mechanisms/algorithms/commit-seq-ordering.md).
