# MVCC atomic multi-key commands

## Scope and guarantees

`tomokv-atomic` changes eligible cross-routed whole-value writes into MVCC groups. Each owner first
installs an invisible per-key version. The group receives one shared `commit_ts` only after its last
owner stamp lands, and that single publication makes every write in the group visible together.
There is no admission ticket, global completion cursor, or incomplete-group frontier.

An eligible cross-shard read samples the global commit clock once at dispatch. Call that value `T`.
A metadata version is normally visible exactly when its shared `commit_ts` is nonzero and
`commit_ts <= T`; the resolver selects the greatest visible `(commit_ts, version_order)` on each
key. A raw predecessor has implicit rank `(0, 0)`. All keys in one write group point at the same
commit record, so a reader cannot observe only part of that group becoming committed.

The installing connection has a narrow read-your-own-writes exception. A pipelined read whose `T`
predates its own preceding write may select that connection's newest uncommitted physical version,
or its newest own committed version above `T`. Other clients' post-snapshot commits remain
invisible. A nonpipelined next read is simpler: the MSET reply is published only after the commit
clock contains the group's timestamp, so its new `T` is at least its own `commit_ts`.

The switch is modifiable and defaults to `no`. `tomokv-atomic-window=-1` derives writer admission
from live writer concurrency and pipeline depth. `tomokv-atomic-reclaim-limit=-1` derives one
process-wide retained-version pool from maxmemory or physical RAM. Both controls park only new
atomic writers; readers and already-admitted work continue so retirement can advance.

> Storage qualification: version-chain preservation, prune-after-grace, and promotion are connected
> end-to-end only for FLAT kvstores. The non-FLAT overwrite tail still uses ordinary predecessor
> disposal and the FLAT prune wrapper is a no-op there.

## Default-OFF path

The atomic admission block is nested under `server.tomo_atomic != 0`. With the switch off, a command
does not read the atomic window or reclaim-pressure state, does not reserve `tomo_atomic_inflight`,
does not allocate a commit record, and uses the ordinary set/delete path. The client-tail,
`csGroup`, and `tomoVerMeta` field substitutions preserve their previous sizes so OFF-mode object
and cache geometry do not change.

The dispatch snapshot branch also requires atomic mode. Raw reads return before testing any MVCC
state. A raw single-owner read therefore does not touch the commit clock. Already-existing version
bags are still resolved correctly if the knob changes while groups are in flight.

## Command coverage

The enabled write set includes:

- MSET, MSETNX, DEL, and UNLINK;
- SINTERSTORE, SUNIONSTORE, SDIFFSTORE, ZUNIONSTORE, ZINTERSTORE, ZDIFFSTORE, and ZRANGESTORE;
- BITOP and PFMERGE;
- RENAME, RENAMENX, and COPY;
- SORT with STORE and GEOSEARCHSTORE.

Source-reading write shapes use the same command snapshot mechanism as cross-routed read-only
commands. MSET installs caller values directly and does not need a source snapshot. Tombstones
represent DEL/UNLINK, empty stores, and the source half of RENAME. MSETNX and other NX destinations
use cancelable value reservations rather than tombstones.

## Commit clock

`commit_clock` is a cache-line-isolated `_Atomic uint64_t`. Its high 63 bits hold the last fully
published timestamp and its low bit is a writer-only publication latch:

- even `2*T` means timestamp `T` is fully published;
- odd `2*T + 1` means a committer is installing timestamp `T+1`, while readers still use `T`.

Readers never spin on the odd state; `tomoCommittedSeq()` acquire-loads the word and shifts right by
one. A successful last-stamp publisher performs:

1. CAS the even clock word to its odd form;
2. release-store `T+1` into the group's shared `commit_ts`;
3. release-store `2*(T+1)` into the clock.

If a reader samples before step 3, it receives the old `T` and excludes the group even if it later
loads the new shared timestamp. If it samples after step 3, the acquire observes all owner stamp
links and the shared timestamp. The short writer interval serializes only timestamp publication;
there is no reader wait and no unfinished group occupying a frontier position.

## Data structures

### Shared `tomoCommit`

Every admitted group allocates one commit record:

| Field | Role |
| --- | --- |
| `_Atomic uint64_t commit_ts` | Zero until the successful last-stamp publication; one timestamp shared by all group versions. |
| `_Atomic unsigned int refs` | One transient group reference plus pre-reserved version references, trimmed to the exact install count before owner operations. |
| `_Atomic unsigned int stamps_pending` | Number of STAMP/CANCEL owner operations still required before sequencing. |
| `size_t reclaim_bytes` | Conservative process-pool charge for the whole group. |
| `csGroup *group` | Valid only until the final stamp/cancel hands the group back to completion. |

A version retains its commit-record reference until the version metadata is unreachable. Physical
object retirement drops it after the post-unlink grace. Sole-value promotion drops it from the
separate metadata-retire callback, after readers can no longer retain the old metadata pointer.

### Per-key metadata

The relevant `tomoVerMeta` fields are:

| Field | Role |
| --- | --- |
| `_Atomic(tomoCommit *) commit` | Shared group visibility record. A zero timestamp is locally uncommitted. |
| `_Atomic(redisObject *) stamped_head` | Per-key head of the unordered stamped index, inherited by every new physical head. |
| `redisObject *stamped_prev` | Link in that unordered stamped index. |
| `redisObject *version_prev` | Physical newest-install-first predecessor. |
| `install_order`, `origin_client_id` | Immutable connection program-order identity used only for own-read widening. |
| `version_order` | Group-local tie break, including duplicate-key last-pair-wins behavior. |
| `owner_ops_pending` | Two for STAMP+PRUNE or one for CANCEL, decremented only by the owner lane. |
| `stamp_state`, `retire_state`, `detached` | Installation, grace, and physical-lifetime state. |
| `reclaim_bytes`, owner/bucket lifecycle fields | Exact per-owner telemetry and reshard-lifecycle protection. |
| `owner_op[2]` | Embedded STAMP/CANCEL and PRUNE carriers, independent of group lifetime. |

The stamped index is not sorted. Commit timestamps do not exist when stamps are linked, and sorting
later would require cross-owner repair. Resolution instead scans the short transient index and
chooses the greatest visible rank. Local prune and raw promotion bound that scan.

### Group and completion state

`csGroup::mset_complete` has three states: zero, `TOMO_COMMIT_INSTALL_READY`, and
`TOMO_COMMIT_FINAL_READY`. `commit_next` is an intrusive link in the ready-group MPSC. The MPSC
contains only a group whose current stage is executable; it never contains admission-order
placeholders.

`mset_pending_count` remains on the real client as the exact relevance gate for the expensive
physical own-version scan. The old per-client pending FIFO, spinlock, drain latch, and ready-client
link are retired layout slots and are not executable state. `mset_next_install_order` remains
IO-owner-written and provides connection-global own-write order without a lock.

## Install-to-commit protocol

### 1. Admission and registration

Admission happens before a fake-ring slot is taken. A finite window uses the inflight counter itself
as the CAS word; zero is unlimited but still counted. Registration sets the group to uncommitted,
captures the current clock for lag diagnostics, allocates its shared commit record, reserves the
connection's install-order range, and release-increments `mset_pending_count`.

Each owner install prepends a metadata version to the physical chain, acquires its immutable
owner/bucket lifecycle reference, charges exact per-owner reclaim telemetry, attaches the shared
commit record, and records the exact `kv`, owner, and group-local order in `mset_installs`. The
transient group reference protects that record during installation. Once the install set closes,
the drainer trims the pre-reserved maximum to the exact group-plus-version reference count once,
before any STAMP/CANCEL can make a version retire; this avoids a contended reference-count RMW for
every MSET key.

### 2. Ready-group MPSC and owner stamps

The last install completion changes the group from zero to `INSTALL_READY`, pushes the group to the
MPSC, and attempts the global drainer election. A losing worker returns immediately. The elected
drainer is retained only because the bounded owner-operation queues are logically SPSC.

For a successful group, the drainer requires the exact expected install count, initializes
`stamps_pending`, sets every version's owner-op count to two, and pushes a zero-sequence STAMP to
each recorded owner. A semantic abort or NX conflict instead assigns no timestamp, sets one owner
operation, and pushes CANCEL for each installed reservation. A zero-install abort goes directly to
the final stage.

STAMP runs under the destination owner's lock. It prepends the version to the current physical
head's stamped index, marks it applied, clears reservation state, and decrements both the version's
owner-op count and the shared stamp count. CANCEL marks the version permanently invisible, clears
its reservation, arms its cancellation grace, and decrements the shared stamp count.

### 3. Last-stamp sequencing

The `stamps_pending` decrements are acquire-release RMWs. Their modification-order chain carries all
prior owner index publications to the worker that observes one. That worker advances the encoded
clock and publishes the shared timestamp. A canceled group skips the clock.

The worker changes the group to `FINAL_READY`, pushes it to the same ready-group MPSC, and attempts
the drainer election. Nothing waits for an earlier admitted group. A slow group is simply absent
until its own last stamp lands, then commits with a later timestamp.

### 4. PRUNE and reply publication

The final-stage drainer validates the shared timestamp and pushes one PRUNE operation per successful
version. PRUNE is therefore always ordered after both the shared `commit_ts` and global clock
publication. Canceled versions have no PRUNE operation beyond their already-completed CANCEL path.

After all owner-affine jobs have been materialized, the group seals its reshard lifecycle, drops its
transient commit-record reference, release-decrements the real client's pending count, and publishes
the group-head CDB byte. Producer notifiers are deduplicated in a word mask for each drain batch.
The CDB publication is the first point at which reassembly may free the group.

## Reader resolution and RYOW

Cross-shard snapshot reads enter a FLAT group pin and sample `T` once. A pure MGET releases the pin
on its last owner after every selected value has been serialized; IO reassembly then consumes only
private output. Other snapshot-reading pipelines retain the pin until their final stage.

`lookupKeyReadWithFlags` preserves two faster cases:

- `vmeta == NULL`: return the raw value without testing atomic mode or loading the clock;
- `TOMO_SINGLE_COMMITTED`: return the sole metadata version directly when an existing pin is not
  older than its timestamp; an unpinned single-owner read needs no clock load.

The slow resolver has two stages:

1. If the real connection's `mset_pending_count` is nonzero, scan the physical chain for the newest
   non-canceled own version. Return it only while its shared timestamp is zero. Encountering a newer
   already-committed own version stops the scan so an older delayed group cannot override it.
2. Scan the unordered stamped index. Select the greatest `(commit_ts, version_order)` at or below
   `T`. Separately remember the own version above `T` with the greatest `install_order`; if one
   exists, it is the RYOW result. A selected tombstone returns absence.

Passing a NULL reader disables both own branches. MSETNX/DEL presence probes use that strict form
with the current commit clock.

The group reply follows clock publication. Even if another committer has latched the clock when a
client's next command samples it, the high bits still contain at least the replying group's
timestamp. This is the response-to-next-read RYOW edge.

## Local retirement

There is no global visibility cursor in retirement. A successful version's PRUNE operation arms a
QSBR callback only after its own timestamp is published. When that grace completes, readers with a
snapshot older than the anchor timestamp have drained, so the owner can remove only physical
versions with a lower `(commit_ts, version_order)` rank. A raw tail has rank zero. Higher committed
versions and zero-timestamp versions are never removed by that callback.

Canceled nodes become eligible only after their own cancellation grace. The physical walk is a
stable filter; survivors retain install order. The stamped index is separately filtered and
release-published from the surviving physical head.

Commit reordering permits a successor callback to reach an obsolete predecessor whose PRUNE is
still queued. The successor grace already licenses logical unlink, but the embedded owner operation
still owns the allocation. In that case pruning removes the predecessor from both live chains and
marks it detached without scheduling physical free. Its eventual PRUNE sees `detached`, schedules
the post-unlink grace, and releases the lifecycle reference after leaving the owner lock.

Physical retirement is always a second grace. It releases the per-owner byte charge and the
version's shared commit-record reference immediately before freeing the object. When one live
committed value remains with no uncommitted sibling, the callback either deletes a sole tombstone or
retires the metadata and promotes a live value back to the raw pinless path.

## Reclaim backpressure

Per-worker cache-line counters remain exact skew telemetry, but admission uses one process-wide
pool. At group completion, the commit record sums every installed version and performs one global
charge. The full conservative group charge remains until its last version metadata retires; this
avoids a global RMW per MSET key and lets a hot worker borrow unused capacity from other workers.

`tomokv-atomic-reclaim-limit` accepts:

- `-1`: one process-wide pool equal to one sixteenth of maxmemory, physical RAM, or allocator memory;
- `0`: disable reclaim accounting/backpressure;
- a positive value: exact process-wide byte cap.

Crossing the cap parks only a newly classified atomic writer before fake-ring allocation. Reads,
owner stamps, finalization, and QSBR continue. When the last metadata reference releases a charged
commit record, the pool is decremented and pressure is refreshed; parked producers are woken when
the pool falls within the cap. A charge also rechecks after publishing pressure, closing the race
where a concurrent last release crosses below the cap before it can observe that publication.

## Observability

INFO exposes the commit-time scheme directly:

| Counter | Meaning |
| --- | --- |
| `tomokv_atomic_commit_ts` | Last fully published global timestamp. |
| `tomokv_atomic_commit_ts_lag` | High-water number of other successful commits that passed a group between registration and its own commit. |
| `tomokv_atomic_stragglers` | Successful groups whose observed commit-ts lag was nonzero. |
| `tomokv_atomic_stamp_full` | Bounded owner-lane full events. |
| `tomokv_atomic_reclaim_limit` | Resolved process-wide byte cap. |
| `tomokv_atomic_reclaim_bytes` | Conservative process-pool charge used for admission. |
| `tomokv_atomic_reclaim_worker_bytes` | Sum of exact per-version owner charges. |
| `tomokv_atomic_reclaim_worker_max` | Largest exact charge on one worker. |
| `tomokv_atomic_reclaim_pressure`, `tomokv_atomic_reclaim_stalls` | Current writer gate and commands parked by it. |

The obsolete `tomokv_atomic_commit_wait_drains` frontier/sequencer witness is removed.

## Memory-order summary

| Edge | Ordering |
| --- | --- |
| Physical metadata and stamped links | Release publication, acquire traversal. |
| Per-version commit pointer | Release attachment at install, acquire reads. |
| Owner-op count and group stamp count | Release initialization, acquire-release decrements. |
| Shared group timestamp | Release store by the last-stamp publisher, acquire reads. |
| Encoded commit clock | Acquire-release latch CAS, release final publication, acquire reader sample. |
| Ready-group MPSC | Release push, acquire exchange; drainer idle is release-published before recheck. |
| Group terminal stage | Release store to `FINAL_READY`, acquire load by the elected drainer. |
| Client pending count | Release increment/decrement, acquire relevance check. |
| CDB reply-ready byte | Release publication after timestamp and PRUNE materialization. |
| Reclaim pressure/pool | Sequentially consistent edge and pool updates, preserving clear-then-rescan. |

## Core invariants

1. Registration and commit-record allocation precede every owner install publication.
2. Before owner operations are armed, the shared record holds exactly one group reference plus one
   reference for every installed version.
3. A successful timestamp is assigned only by the worker that completes the last owner stamp.
4. The shared timestamp is zero until every installed version is linked in its owner stamped index.
5. Readers sample one nonblocking global `T`; a non-own result never uses `commit_ts > T`.
6. PRUNE is materialized only after the group timestamp and global clock are fully published.
7. Retirement uses the callback anchor's local timestamp, never a global cursor.
8. A pending embedded owner operation prevents physical free, but not successor-grace unlink.
9. STAMP/PRUNE/CANCEL mutations run under the recorded owner lock, ahead of normal owner work.
10. Reply publication follows successful commit publication or completion of every cancellation.
11. Reassembly is the exactly-once atomic admission retirement point.
12. OFF mode does not enter atomic admission, allocation, snapshot, or completion machinery.

## Implementation map

| Area | Files/functions |
| --- | --- |
| Commit clock, admission, pooled reclaim, commit-record lifetime | `src/server.c` |
| Owner lane, ready-group MPSC, resolver, final reply publication | `src/server.c` |
| Shared record and version metadata layouts/helpers | `src/object.h` |
| Group/client layouts and public retirement APIs | `src/server.h` |
| Version install, stamp, cancel, prune, and promotion | `src/db.c` |
| Post-grace object/metadata commit-reference release | `src/flatstore.c` |
| Knob definitions and live apply | `src/config.c` |
| Knob acceptance cells | `tools/preflight/knob_matrix.sh` |
