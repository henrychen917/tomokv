# MVCC atomic multi-key commands and own-read

## What this implementation is

`tomokv-atomic` changes newly admitted cross-routed whole-value writes from ordinary owner-local replacement/deletion into groups of per-key versions that install first and join the global committed frontier through one group sequence later. The switch is modifiable and defaults to `0`; `tomokv-atomic-window` is modifiable, accepts `0..INT_MAX`, and defaults to `64`. (`src/config.c:3182-3184`, `src/server.c:8344-8387`, `src/server.c:10303-10333`, `src/server.c:10363-10377`)

The global visibility frontier is the cache-line-isolated `_Atomic uint64_t commit_seq`; snapshot draws acquire-load it, while a successful group release-stores its ticket only after all of that group's STAMP jobs have been queued. (`src/server.c:280-301`, `src/server.c:427-435`, `src/server.c:10312-10333`, `src/server.c:10363-10383`)

In enabled mode, eligible cross-shard reads use a snapshot drawn once at dispatch, and an owner-local resolver maps each key's version bag to that snapshot. A read by the installing connection may instead select its own still-uncommitted version or widen past the snapshot to its own already-stamped version. (`src/server.c:8465-8471`, `src/server.c:10133-10148`, `src/server.c:10206-10256`)

The active own-read implementation does not wait for an earlier atomic group to commit; dispatch explicitly proceeds, and `kvobjVersionAt` resolves the connection's own version on the key owner. (`src/server.c:8280-8281`, `src/server.c:10133-10256`)

> **Storage qualification:** the implemented prune-after-grace and metadata-promotion path is connected only to FLAT kvstores. Non-FLAT versioned overwrite also sends the predecessor through ordinary defer/free/decref handling, so the code does not establish the predecessor lifetime required by the bag in that storage mode. (`src/server.c:5561-5580`, `src/server.c:6117-6121`, `src/db.c:856-861`, `src/db.c:904-917`, `src/kvstore.c:91-94`)

## Default OFF path versus ON path

### Default: `tomokv-atomic` OFF

The admission block is nested under `server.tomo_atomic != 0`; with the switch off, a new command neither reads `tomokv-atomic-window` nor reserves `tomo_atomic_inflight`, and `atomic_write_admission` remains zero. (`src/server.c:8338-8387`)

`dispatchGather` derives `atomic_write` only from the captured admission marker, so a command admitted while OFF cannot become versioned merely because the configuration changes during group construction. (`src/server.c:13519-13530`, `src/server.c:13642-13662`)

On this path MSET and the MSETNX write wave call ordinary `setKey`, while DEL/UNLINK call `dbSyncDelete` for each present key. (`src/server.c:11668-11760`, `src/server.c:11762-11777`)

An OFF-mode cross-shard read does not enter the dispatch-time `commit_seq` pin branch, because that branch also requires `server.tomo_atomic != 0`. (`src/server.c:8465-8471`)

OFF does not mean that already-existing version bags are ignored: when a lookup finds a non-NULL `vmeta`, `lookupKeyReadWithFlags` still calls `kvobjVersionAt`; the knob only gates the `single_state` fast-license branch. (`src/db.c:366-397`)

An already-admitted versioned group also keeps the captured admission marker through construction and completion even if the live configuration later turns OFF. (`src/server.c:8344-8387`, `src/server.c:13519-13526`)

### `tomokv-atomic` ON

Admission first requires a command with `TOMO_R_CROSS`, then classifies MSET, `CS_DEL`, MSETNX, or an allowed PORTALL whole-value shape as an atomic write. (`src/server.c:8346-8365`)

The implemented command coverage is:

| Family | Admitted forms |
| --- | --- |
| Original bag writers | MSET, MSETNX, DEL, and UNLINK; DEL and UNLINK share `CS_DEL`, and one-key DEL is specially enrolled when the normal classifier returns no row. (`src/server.c:8350-8362`, `src/server.c:10789-10796`) |
| Set stores | SINTERSTORE, SUNIONSTORE, and SDIFFSTORE through `CS_SSTORE`. (`src/server.c:592-603`, `src/server.c:10835-10846`) |
| Sorted-set stores | ZUNIONSTORE, ZINTERSTORE, and ZDIFFSTORE through `CS_ZSTORE`, plus ZRANGESTORE. (`src/server.c:592-603`, `src/server.c:10867-10890`) |
| String/HLL stores | BITOP and PFMERGE. (`src/server.c:592-603`, `src/server.c:10914-10921`) |
| Whole-key moves/copies | RENAME, RENAMENX, and COPY. (`src/server.c:592-603`, `src/server.c:10814-10826`) |
| Conditional shapes | SORT only when the proc is `sortCommand` and the invocation has a destination; GEO only when the proc is `geosearchstoreCommand`. (`src/server.c:604-608`, `src/server.c:10888-10905`) |

The source-reading shapes are marked `TOMO_R_ATOMIC_READ`; GET, MGET, EXISTS, TOUCH, cross-routed read-only commands, and the explicit source-reading write types receive the same routing bit. (`src/server.c:614-647`, `src/server.c:11052-11066`)

After execution state moves to a fake, dispatch enters a FLAT group pin and acquire-loads `commit_seq` exactly when atomic mode is ON, the command is cross-routed, and the command is either read-only or is an admitted write with `TOMO_R_ATOMIC_READ`. (`src/server.c:8450-8471`)

The pipeline, atomic-snapshot gather, SORT, and two-hop constructors copy the dispatch snapshot into `g->read_seq`; `tomoPinnedReadSnapshot` can reuse a direct client pin, that group snapshot, or the group head's pin without loading the frontier again. (`src/server.c:12953-12956`, `src/server.c:13636-13641`, `src/server.c:14340-14343`, `src/server.c:14412-14415`, `src/server.h:5881-5901`)

A raw single-owner read does not load `commit_seq`: it returns directly when `vmeta == NULL`; an unpinned read draws the frontier lazily only after it encounters a version bag. (`src/db.c:366-371`, `src/db.c:394-397`, `src/server.c:427-435`)

## Key data structures

### Global commit controller

The frontier and the state that serializes commits occupy separate aligned cache lines. (`src/server.c:280-301`)

| Field | Implemented role |
| --- | --- |
| `_Atomic uint64_t commit_seq` | Highest group sequence published to readers; loaded with `memory_order_acquire` and stored with `memory_order_release`. (`src/server.c:289-301`, `src/server.c:427-429`, `src/server.c:10369-10377`) |
| `_Atomic uint64_t next_seq` | Ticket source; a successful group takes `fetch_add(..., memory_order_relaxed) + 1` while the global commit lock is held. (`src/server.c:292-301`, `src/server.c:10303-10310`) |
| `atomic_flag commit_lock` | Serializes ticket draw, owner-op materialization, global queue append, and frontier publication; acquisition uses `memory_order_acquire` and release uses `memory_order_release`. (`src/server.c:292-301`, `src/server.c:9802-9825`) |
| `csGroup *commit_head`, `*commit_tail` | Global FIFO links for groups whose STAMP/CANCEL jobs have been materialized and that await frontier/reply publication. (`src/server.c:292-301`, `src/server.c:10330-10333`, `src/server.c:10363-10367`) |

### Owner operations and states

`tomoOwnerOp` is `{redisObject *kv, uint64_t seq, tomoOwnerOpKind kind}`; its kinds are `TOMO_OWNER_OP_STAMP`, `TOMO_OWNER_OP_PRUNE`, and `TOMO_OWNER_OP_CANCEL`. (`src/object.h:105-115`)

Stamp state is `PENDING`, `APPLIED`, or `CANCELED`; retirement state is `ACTIVE`, `PRUNE_GRACE`, or `PHYSICAL`. (`src/object.h:117-127`)

Reservations use `TOMO_RESERVATION_SIGNAL_SET` or `TOMO_RESERVATION_SILENT`, and the single-version read license uses `NONE`, `COMMITTED`, or `SUPERSEDED`. (`src/object.h:129-135`)

### Per-key `tomoVerMeta`

Every `redisObject` has a nullable `vmeta`; `kvobjVmeta` acquire-loads the pointer and `kvobjSetVmeta` release-stores it. (`src/object.h:182-198`, `src/object.h:219-225`)

`TOMO_VERSION_UNCOMMITTED` is `UINT64_MAX`. (`src/object.h:180`)

| Field | Implemented role |
| --- | --- |
| `_Atomic uint64_t version_seq` | Starts as the uncommitted sentinel for an atomic install and is release-stamped with the group's nonzero ticket; resolver reads use acquire loads. (`src/db.c:469-496`, `src/db.c:996-999`, `src/server.c:10137-10143`, `src/server.c:10246-10251`) |
| `_Atomic(redisObject *) committed_head` | Per-key cursor inherited by a new physical head and release-updated by STAMP or prune repair; the resolver acquire-loads it before walking committed history. (`src/db.c:476-494`, `src/db.c:1002-1009`, `src/db.c:1284-1289`, `src/server.c:10242-10244`) |
| `uint64_t install_order` | Receives a connection-global number `mset_install_order_base + ii`; no executable resolver or committed-chain insertion in this tree reads this field. (`src/server.c:9946-9950`, `src/server.c:11432-11448`, `src/server.c:10133-10147`, `src/db.c:976-993`) |
| `uint64_t origin_client_id` | Receives the real connection id at install and is compared for both own-uncommitted selection and committed own-widening. (`src/server.c:11440-11448`, `src/server.c:10137-10146`, `src/server.c:10242-10253`) |
| `uint32_t version_order` | Receives the group-local install index and breaks ties between same-sequence versions in the committed chain. (`src/server.c:11435-11451`, `src/db.c:976-991`) |
| `int16_t install_owner`, `uint16_t install_bucket`, `uint8_t lifecycle_ref_held` | Record the owner/bucket lifecycle slot acquired for the install and released after owner-affine work and any armed prune callback. (`src/server.c:367-397`, `src/server.c:11444-11448`, `src/db.c:1134-1141`) |
| `uint8_t version_tombstone` | Marks a payload that resolves as logical absence and is excluded from single-live-version promotion. (`src/server.c:10144-10146`, `src/server.c:10255-10256`, `src/db.c:1061-1071`, `src/db.c:1356-1369`) |
| `uint8_t version_reservation`, `void *reservation_owner` | Mark MSETNX/NX destination reservations and identify the group allowed to reuse its own reservation. STAMP and CANCEL clear both. (`src/server.c:11454-11468`, `src/server.c:11495-11504`, `src/db.c:997-1000`, `src/db.c:1035-1037`) |
| `_Atomic uint8_t version_canceled` | Release-set before CANCEL is queued; the own-uncommitted scan acquire-loads it and skips the version immediately. (`src/server.c:10320-10328`, `src/server.c:10137-10143`) |
| `uint8_t stamp_state` | Constructor sets `PENDING` for the uncommitted sentinel and `APPLIED` otherwise; STAMP changes it to `APPLIED`, while CANCEL changes it to `CANCELED`. (`src/db.c:469-501`, `src/db.c:996-1000`, `src/db.c:1028-1037`) |
| `uint8_t retire_state` | Constructor sets `ACTIVE`; owner operations and grace callbacks transition it through `PRUNE_GRACE` and `PHYSICAL`. (`src/db.c:495-501`, `src/db.c:927-941`, `src/db.c:1042-1048`, `src/db.c:1089-1105`) |
| `uint8_t detached` | Marks a bag removed from the live table by an ordinary write/delete; detached terminal versions go directly to physical retirement instead of mutating a live bag. (`src/db.c:1108-1131`, `src/db.c:1042-1048`, `src/db.c:1097-1100`) |
| `_Atomic uint8_t single_state` | Read fast-path license; a successor release-stores `SUPERSEDED`, and an eligible sole committed live version can be release-published as `COMMITTED`. (`src/db.c:482-489`, `src/db.c:1051-1086`, `src/object.h:227-230`) |
| `_Atomic unsigned int owner_ops_pending` | Materialized as `2` for STAMP+PRUNE or `1` for CANCEL, then decremented with `memory_order_acq_rel` by the owner lane. (`src/server.c:10320-10327`, `src/server.c:10006-10035`) |
| `redisObject *version_prev` | Physical newest-install-first predecessor, assigned when the new version is constructed and traversed by own-uncommitted resolution and pruning. (`src/db.c:469-501`, `src/server.c:10137-10147`, `src/db.c:1212-1243`) |
| `redisObject *committed_prev` | Separate committed-order predecessor, release-linked by STAMP/prune and acquire-followed by the resolver. (`src/object.h:247-255`, `src/db.c:976-1009`, `src/server.c:10246-10253`) |
| `kvstore *version_kvs`, `redisDb *version_db` | Retain the owning key store and DB for stamp/cancel/prune lookup, deletion, and notifications. (`src/db.c:469-501`, `src/db.c:1028-1048`, `src/db.c:1275-1281`, `src/server.c:10014-10020`) |
| `tomoOwnerOp owner_op[2]` | Embedded storage for STAMP/CANCEL in slot 0 and PRUNE in slot 1, so queued jobs do not depend on group storage. (`src/object.h:160-167`, `src/server.c:10320-10328`) |

The physical and committed chains are distinct: install prepends through `version_prev`, while STAMP inserts through `committed_prev` in descending `(version_seq, version_order)` order and publishes the resulting maximum through the physical head's `committed_head`. (`src/db.c:856-861`, `src/db.c:967-1009`)

### Group and connection state

`csMsetInstall` records the exact installed `kv`, its sole owner, and a 32-bit group-local install index. (`src/server.h:2102-2106`)

| Structure | Relevant fields and role |
| --- | --- |
| `csGroup` | `version_seq` is the uncommitted marker/write ticket, `read_seq` is the command snapshot, `commit_next` is the global queue link, and `mset_client` plus `mset_pending_prev/next` link the group into its real connection's FIFO. (`src/server.h:2133-2138`) |
| `csGroup` | Atomic `mset_complete` and `mset_install_count`, `mset_installs`, `mset_install_order_base`, `versioned_write`, expected/ready/abort/NX flags, atomic `msetnx_retry`, and `msetnx_state` carry installation and completion state. (`src/server.h:2139-2151`) |
| `csGroup` | `key_sig`, `key_h`, and `key_h_n` retain written-key hashes, although the active resolver does not consume them. (`src/server.h:2115-2132`, `src/server.c:10101-10107`, `src/server.c:10133-10256`) |
| Real-client execution tail | `mset_pending_head/tail` is the registration FIFO, `mset_next_install_order` reserves connection-global order ranges, and `mset_pub` points at the legacy publishing-record ring. (`src/server.h:1783-1795`) |
| Real-client execution tail | `mset_pending_lock`, `mset_drain_latch`, and atomic `mset_pending_count` serialize FIFO operations, elect one per-client drainer, and gate the own-uncommitted scan. (`src/server.h:1839-1849`, `src/server.c:9827-9837`, `src/server.c:10227-10240`) |
| Real-client execution tail | `atomic_window_parked_node` and `atomic_window_parked_tid` track a command refused by the admission window before it takes a fake-ring slot. (`src/server.h:1789-1795`, `src/server.h:1853-1858`, `src/server.c:497-515`) |

The lifecycle table is lazily allocated as one atomic counter per `(worker, bucket)`; each install records and release-increments its slot, and release uses an acquire-release decrement. (`src/server.c:325-397`)

At install, `tomoAtomicLifecycleAcquire` asserts that the routed owner still owns the computed bucket. At owner-op consumption and prune-callback entry, `tomoAtomicOwnerCheck` only increments a relaxed stale-owner diagnostic on mismatch; it does not abort, redirect, or fail the operation. (`src/server.c:367-384`, `src/server.c:411-425`, `src/server.c:10003-10010`, `src/db.c:1144-1150`)

Before a reshard enters its producer-drain phase, the coordinator sequentially-consistent-closes atomic admission and waits until `tomo_atomic_unsealed == 0` and the source range's lifecycle-reference sum is zero. (`src/server.c:15865-15939`)

## Atomic memory-order map

| Publication edge | Ordering in the code |
| --- | --- |
| `kvobj::vmeta` | Acquire load / release store. (`src/object.h:219-225`) |
| Version sequence | Resolver/helper acquire loads; STAMP release store. (`src/object.h:232-235`, `src/db.c:996-999`, `src/server.c:10246-10251`) |
| Committed cursor and predecessor links | Acquire loads / release stores. (`src/object.h:247-255`, `src/db.c:1002-1009`, `src/server.c:10242-10253`) |
| Group completion | `mset_complete` release store; FIFO-head acquire load. (`src/server.c:10336-10346`, `src/server.c:10272-10279`) |
| Per-client drainer election | Strong CAS success is acquire, failure is relaxed; latch clear is release. (`src/server.c:10343-10359`) |
| Global commit lock | `atomic_flag` acquire on lock and release on unlock. (`src/server.c:9802-9825`) |
| Ticket draw | Relaxed fetch-add on `next_seq`, inside the global lock. (`src/server.c:10303-10310`, `src/server.c:10349-10364`) |
| Global frontier | Successful commit release-stores `commit_seq`; snapshot reads acquire-load it. (`src/server.c:10369-10377`, `src/server.c:427-429`, `src/server.c:8465-8471`) |
| Cancel decision | `version_canceled` release store; own scan acquire load. (`src/server.c:10320-10323`, `src/server.c:10140-10143`) |
| Owner-op count | Release store at materialization; owner decrements are acquire-release. (`src/server.c:10320-10327`, `src/server.c:10011-10035`) |
| Owner lane availability | `stamp_pending` release increment/decrement; consumers acquire-load before drain. (`src/server.c:10047-10056`, `src/server.c:10060-10087`, `src/server.c:21889-21893`) |
| Admission counters | `tomo_atomic_inflight` uses relaxed increment/CAS/decrement; admission increments `tomo_atomic_unsealed` with sequential consistency and sealing decrements it with acquire-release. (`src/server.c:460-472`, `src/server.c:541-544`, `src/server.c:15313-15324`) |

## Install-then-commit protocol

### 1. Reserve admission before taking a ring slot

The bounded-admission block is the final gate before fake-ring allocation; refusal leaves `dispatchid` unchanged and the decoded pending command at the executable input head. (`src/server.c:8338-8345`)

For `window == 0`, admission relaxed-increments `tomo_atomic_inflight`, sequentially-consistent-increments `tomo_atomic_unsealed`, and succeeds unconditionally. (`src/server.c:457-465`)

For a finite window, a relaxed CAS loop increments `tomo_atomic_inflight` only while the observed value is below the window; success also sequentially-consistent-increments `tomo_atomic_unsealed`, and failure parks the client. (`src/server.c:466-476`, `src/server.c:8377-8385`)

The cutover gate is checked with sequential consistency before reservation and rechecked after reservation; losing the post-reservation race removes both counts and parks the command. (`src/server.c:517-539`, `src/server.c:8363-8384`)

### 2. Pin a source snapshot when the shape requires one

After the fake is populated, an eligible cross-shard read or source-reading atomic write enters the FLAT group pin and takes one acquire load of `commit_seq`. (`src/server.c:8450-8471`)

MSET does not appear in `csAtomicReadsSources`, while MSETNX and DEL do, so the latter commands satisfy the dispatch pin predicate. Their explicit owner-side presence checks nevertheless ignore `g->read_seq`: they call `tomoCommittedSeq()` at execution and pass a NULL reader. (`src/server.c:614-647`, `src/server.c:11062-11066`, `src/server.c:8465-8471`, `src/server.c:11484-11493`, `src/server.c:11513-11515`)

### 3. Register the group before owner publication

`csMsetRegister` sets `versioned_write = 1`, sets the group's sequence to `TOMO_VERSION_UNCOMMITTED`, binds the real client, and asserts that install storage, a positive expected count, and a nonzero key signature already exist. (`src/server.c:9914-9922`)

Under `mset_pending_lock`, registration checks order-range overflow, reserves `version_install_expected` consecutive numbers from the real client's `mset_next_install_order`, appends the group to that connection's FIFO, and release-increments `mset_pending_count`. (`src/server.c:9946-9957`)

The MSET/DEL coalesced builder registers only after computing all routed owners and the written-key hashes, then pushes owner subs; MSETNX's first owner-ordered wave likewise registers before its first push. (`src/server.c:12639-12705`, `src/server.c:12794-12799`)

### 4. Install fresh physical versions on key owners

`setKeyVersioned` selects the version-aware add/overwrite implementation and passes the group's current uncommitted sentinel into metadata creation. (`src/db.c:1560-1572`, `src/db.c:1583-1627`)

For an existing key, the new object's metadata points `version_prev` at the old physical head and inherits that head's committed cursor before the new table head is published. (`src/db.c:469-501`, `src/db.c:856-861`)

On a FLAT kvstore, a versioned overwrite does not retire the predecessor; only a non-versioned overwrite calls the raw retire path at this point. (`src/db.c:904-910`)

`csMsetRecordInstall` takes a relaxed fetch-add index, checks it against the expected count, writes `install_order = base + ii` and the real connection id, acquires the owner/bucket lifecycle reference, writes `version_order = ii`, and fills `mset_installs[ii]`. (`src/server.c:11432-11451`)

The `ii` assigned to an install is the value returned by `mset_install_count`'s relaxed fetch-add when that owner records the object; it is not read from the command's argument position. (`src/server.c:11432-11451`)

MSET installs and records one supplied value per pair. (`src/server.c:11542-11599`)

DEL/UNLINK resolves committed state for its reply, but installs and records an empty-placeholder tombstone for every argument position, including absent and duplicate keys. (`src/server.c:11509-11539`)

MSETNX uses value reservations rather than tombstones; its exact path is described in [MSETNX reservations and cancellation](#msetnx-reservations-and-cancellation). (`src/server.c:11477-11505`)

The other admitted whole-value shapes install one destination version, except RENAME/RENAMENX, which expect a destination value plus a source tombstone. (`src/server.c:13619-13650`, `src/server.c:14443-14468`, `src/server.c:12120-12137`)

### 5. Mark completion and elect one per-client drainer

The last final owner stage calls `csMsetInstallDone`; intermediate MSETNX/NX or read stages publish only a stage-ready byte and continue later. (`src/server.c:22144-22199`)

`csMsetInstallDone` release-stores `mset_complete = 1`; a strong acquire CAS from `0` to `1` on the real client's `mset_drain_latch` elects the drainer, and a loser returns. (`src/server.c:10336-10347`)

The elected drainer acquires the global commit lock, pops consecutive complete heads from this connection's pending FIFO, release-clears the latch, rechecks the FIFO head, and reacquires the latch if completion raced with the clear. (`src/server.c:10349-10361`)

`csMsetPopComplete` refuses a missing or incomplete head, so completion may arrive out of order but ticket processing for one connection follows registration FIFO order. (`src/server.c:10272-10287`)

If a worker contends for `commit_lock`, its wait loop drains that same worker's owner-op lane when necessary, breaking the bounded-lane/lock dependency while retaining acquire/release lock semantics. (`src/server.c:9790-9825`)

### 6. Draw a ticket and materialize STAMP or CANCEL

For a non-canceled group, `csMsetStampAndAppend` asserts that the installed count equals `version_install_expected` and takes `fetch_add(next_seq, 1, relaxed) + 1`. (`src/server.c:10293-10310`)

`version_abort` or any MSETNX position in `CS_MSETNX_PRESENT` makes the group canceled; the group uses sequence `0`, and MSETNX records `CS_ERR_NX_EXISTS`. (`src/server.c:10294-10311`)

For every installed object, the commit path asserts the uncommitted sentinel and matching group-local order, release-stores the cancel bit and owner-op count, fills embedded STAMP/CANCEL and optional PRUNE records, and pushes STAMP or CANCEL to the recorded owner. (`src/server.c:10312-10329`)

Only after those first owner jobs have been pushed is the group appended to `commit_head/commit_tail`. (`src/server.c:10328-10333`)

### 7. Publish the global frontier, then PRUNE and reply

While still holding `commit_lock`, the drainer removes every group from the global queue in FIFO order. (`src/server.c:10363-10367`, `src/server.c:10402-10403`)

For a successful group it release-stores the group's ticket into `commit_seq`, then pushes each PRUNE job; a canceled group neither advances `commit_seq` nor has PRUNE jobs. (`src/server.c:10369-10386`)

After all possible owner jobs for the group exist, the path acquire-release-decrements `tomo_atomic_unsealed`, publishes the group-head reply-ready slot, and release-decrements the connection's `mset_pending_count`. (`src/server.c:541-544`, `src/server.c:10387-10400`)

The implemented successful-group ordering is therefore: all STAMP enqueues, then `commit_seq` release publication, then all PRUNE enqueues, then reply-ready and pending-count publication. (`src/server.c:10312-10333`, `src/server.c:10363-10400`)

### 8. Apply owner operations under the owner lock

`csStampPush` selects the recorded owner's reserved lane, queues the tagged embedded op, release-increments `stamp_pending`, release-publishes the queue tail, and advertises the lane. (`src/server.c:9979-9981`, `src/server.c:10060-10087`)

`csStampDrain` acquire-checks `stamp_pending`, pops batches, takes `tomoWkrLock(worker->id)`, and applies every STAMP, PRUNE, or CANCEL before unlocking. (`src/server.c:9983-10041`)

STAMP requires a nonzero sequence, calls `tomoApplyVersionStamp`, and acquire-release-decrements `owner_ops_pending` from `2`; reservation-backed MSETNX also emits its deferred modification notification in this arm. (`src/server.c:10006-10021`)

PRUNE requires a nonzero sequence, acquire-release-decrements `owner_ops_pending` from `1`, and calls `tomoArmVersionRetire`. (`src/server.c:10022-10029`)

CANCEL requires sequence `0`, acquire-release-decrements `owner_ops_pending` from `1`, and calls `tomoCancelVersion`. (`src/server.c:10030-10036`)

The worker checks and drains this reserved lane at the beginning of a slice and again before executing any already-popped normal batch. (`src/server.c:21889-21893`, `src/server.c:21994-22004`)

STAMP may execute before the group's frontier publication because its job is queued first; it release-writes `version_seq`, marks the object applied, clears reservation state, and release-links it into the committed chain. (`src/server.c:10312-10329`, `src/db.c:944-1010`)

### 9. Retire the admission slot at terminal reassembly

Commit publication does not decrement `tomo_atomic_inflight`; the group's single terminal reassembly point does so with a relaxed fetch-sub. (`src/server.c:15303-15315`)

A sequentially-consistent fence follows that decrement before the waiter count is tested and parked producers are woken. (`src/server.c:15316-15324`)

The finite window therefore counts admitted groups through IO-side group teardown, while `tomo_atomic_unsealed` stops counting earlier when all owner-affine jobs have been materialized. (`src/server.c:10387-10389`, `src/server.c:15306-15324`)

## Read resolution and OWN-READ

### Lookup integration

`lookupKeyReadWithFlags` first performs the ordinary table lookup; a NULL metadata pointer preserves the raw-head return path without testing atomic mode or drawing a frontier. (`src/db.c:361-371`)

When atomic mode is ON, `TOMO_SINGLE_COMMITTED` licenses a direct return if the command has no pinned snapshot or the version's acquire-loaded sequence is no greater than the pin. (`src/db.c:372-384`)

If that sole version is newer than the pin, or if the metadata head lacks the license, lookup calls `kvobjVersionAt` with the pinned or current snapshot and the current client. (`src/db.c:385-397`)

### Stage 1: own uncommitted version

`kvobjVersionAt` returns a raw head immediately and otherwise canonicalizes a fake reader to its real parent. (`src/server.c:10206-10213`)

For a real reader, the own physical-chain scan is skipped on a worker only when both the connection's acquire-loaded `mset_pending_count` is zero and that worker's acquire-loaded `stamp_pending` is zero; non-worker resolve contexts retain the scan. (`src/server.c:10215-10238`)

`csMsetOwnVersionAt` walks `version_prev` from the physical head, skips any object whose acquire-loaded sequence is not the uncommitted sentinel or whose acquire-loaded cancel bit is set, and selects the first object whose `origin_client_id` matches the real connection. (`src/server.c:10133-10145`)

The scan does not compare numeric `install_order`; its ordering comes from the physical newest-install-first chain. (`src/server.c:10133-10147`, `src/db.c:856-861`)

If the selected own object is a tombstone, the resolver sets `found` and returns logical absence rather than continuing to an older value. (`src/server.c:10144-10147`)

### Stage 2: committed cursor with own-widening

If no own uncommitted object is selected, the resolver acquire-loads the physical head's `committed_head` and walks `committed_prev`. (`src/server.c:10242-10253`)

For a metadata node it stops at the first sequence `<= snapshot`; for a real reader it also stops at the first node with the same `origin_client_id` even when that sequence is above the snapshot. (`src/server.c:10242-10253`)

A raw tail is returned when reached, and a selected committed tombstone returns `NULL`. (`src/server.c:10246-10256`)

Passing `reader_connection == NULL` disables both the own-uncommitted scan and own-widening, because there is no real client and `reader_id` becomes zero. (`src/server.c:10210-10213`, `src/server.c:10227-10243`, `src/server.c:10251-10256`)

MSETNX and DEL use that NULL-reader form for their owner-side committed presence probes. (`src/server.c:11484-11493`, `src/server.c:11513-11515`)

STAMP deliberately leaves `origin_client_id` intact, so an own read can widen to an already-stamped group whose ticket is still above its dispatch snapshot. (`src/db.c:1011-1021`, `src/server.c:10249-10253`)

### Single-version license

`tomoPublishSingleCommitted` refuses detached or tombstone objects, non-applied stamps, a state other than `TOMO_SINGLE_NONE`, pending owner ops, a cursor not equal to the object, or any committed predecessor. (`src/db.c:1061-1071`)

It also refuses a physical predecessor unless that predecessor is fully canceled with zero pending owner ops; only then does it release-store `TOMO_SINGLE_COMMITTED`. (`src/db.c:1073-1086`)

A later install release-stores `TOMO_SINGLE_SUPERSEDED` into the previous metadata before publishing the new head, preventing that predecessor from regaining the fast license. (`src/db.c:477-490`)

## Tombstones, DEL/UNLINK, and MSETNX

### DEL/UNLINK tombstones

Atomic DEL/UNLINK calls `kvobjVersionAt(head, tomoCommittedSeq(), NULL)` to decide whether the key contributes to the reply, then installs a tombstone regardless of the probe result. (`src/server.c:11509-11530`)

Only a live, nonduplicate argument increments the deleted count and emits modification/event/dirty accounting; every argument still contributes an installed tombstone to the group. (`src/server.c:11515-11539`)

The resolver turns a selected tombstone into absence in both the own-uncommitted and committed stages. (`src/server.c:10144-10147`, `src/server.c:10255-10256`)

Empty destination stores also use `csInstallVersionTombstone`, and atomic RENAME installs a source tombstone rather than physically deleting the source during its read hop. (`src/server.c:11321-11337`, `src/server.c:12068-12084`, `src/server.c:12120-12137`)

Physical deletion of a sole committed tombstone occurs later in `tomoVersionPruneAfterGrace` under the owner lock. (`src/db.c:1345-1372`)

### MSETNX reservations and cancellation

MSETNX reservation state per position is `PENDING`, `RESERVED`, or `PRESENT`. (`src/server.c:223-225`, `src/server.h:2147-2150`)

Reservation acquisition repeatedly selects the lowest owning worker among still-pending positions, builds one normal owner-queue wave for that worker, and retries conflicting positions behind owner FIFO order. (`src/server.c:12710-12718`, `src/server.c:12746-12799`)

On the owner, `csMsetnxHasOtherReservation` rejects a pending reservation only when it belongs to another group; a reservation from the same group is allowed. (`src/server.c:11454-11468`)

The owner then performs a committed-only presence check with a NULL reader; an existing value marks the position `PRESENT`. (`src/server.c:11484-11493`)

If absent, the owner installs the requested value as an uncommitted version, sets `version_reservation = TOMO_RESERVATION_SIGNAL_SET`, sets `reservation_owner = g`, records the install, and marks the position `RESERVED`. (`src/server.c:11495-11505`)

If any position becomes `PRESENT`, `csMsetStampAndAppend` cancels the whole group, assigns no ticket, and release-marks every already-installed reservation canceled before queuing its CANCEL op. (`src/server.c:10294-10310`, `src/server.c:10312-10328`)

CANCEL leaves `version_seq` at the uncommitted sentinel, sets stamp state to `CANCELED`, clears reservation fields, and arms prune grace for an attached version or physical retirement for a detached one. (`src/db.c:1024-1049`)

The reassembler replies zero for `CS_ERR_NX_EXISTS`, one for a successfully committed reservation group, and an error for any other group error. (`src/server.c:15213-15218`)

MSETNX therefore does not create tombstone versions; it creates cancelable value reservations and either stamps all successful positions with one ticket or cancels every installed reservation with sequence zero. (`src/server.c:11477-11505`, `src/server.c:10294-10329`)

## Prune-after-grace and physical retirement

### STAMP and CANCEL transitions

`tomoApplyVersionStamp` requires nonzero/non-sentinel input, `PENDING` stamp state, and an uncommitted object. (`src/db.c:944-950`)

For an attached bag it finds the current physical table head and reads that head's committed cursor; for a detached bag it does not move a live cursor. (`src/db.c:951-969`)

It inserts the object into the committed chain in descending `(version_seq, version_order)`, release-stores the ticket, marks `APPLIED`, clears reservation fields, and release-publishes either the predecessor link or new committed maximum. (`src/db.c:971-1010`)

`tomoCancelVersion` requires `PENDING`, the uncommitted sentinel, and zero remaining owner ops; it marks `CANCELED`, clears reservation state, and transitions an attached `ACTIVE` object to `PRUNE_GRACE`. (`src/db.c:1028-1048`)

### PRUNE arm

`tomoArmVersionRetire` requires an applied version with the matching sequence, that sequence no greater than the acquire-loaded global frontier, and zero owner ops. (`src/db.c:1089-1096`, `src/server.c:427-429`)

An attached `ACTIVE` version becomes `PRUNE_GRACE` and is passed to `kvstoreFlatRetireVersionPrune`; an already-detached active version goes directly to physical retirement. (`src/db.c:1097-1105`)

Physical retirement requires an applied or canceled terminal stamp and zero owner ops, changes the state to `PHYSICAL` once, and calls the ordinary FLAT raw-retire wrapper. (`src/db.c:922-942`)

### Grace callback

FLAT retire payload dispatch invokes `tomoVersionPruneAfterGrace` for a version-prune record after grace. (`src/flatstore.c:25-51`, `src/flatstore.c:187-196`)

The callback publishes entry into the worker's FLAT section, waits out an active FLAT resize, and takes the executing owner's worker lock before reading or changing a live bag. (`src/db.c:1144-1164`)

A missing/already-physical anchor exits; a detached `PRUNE_GRACE` anchor returns to `ACTIVE`, enters physical retirement, and exits. (`src/db.c:1165-1177`)

For a live committed anchor, `retire_max` is the anchor's own sequence rather than the current `commit_seq`; for a canceled anchor it is zero. (`src/db.c:1180-1206`)

The physical-chain walk retires canceled nodes only after their own grace has returned them to `ACTIVE` and their owner-op count is zero. (`src/db.c:1208-1224`)

For a committed anchor, it also retires nodes below `retire_max`, but excludes an uncommitted node, a node above the currently visible frontier, a non-applied node, or a node with pending owner ops. (`src/db.c:1224-1238`)

Unlinking is a stable filter of `version_prev`; a successful committed callback separately stable-filters `committed_prev` to remove objects already marked `PHYSICAL`. (`src/db.c:1233-1268`)

If no physical survivor remains, the callback deletes the key with `dbSyncDelete`. (`src/db.c:1269-1282`)

If the physical head changes, the callback release-publishes the repaired committed cursor and updates the table head; it also transitions whole-key expiration and hash-field subexpiration indexing to the new physical head. (`src/db.c:1284-1320`)

If exactly one committed version and no uncommitted version remain, an eligible sole tombstone is synchronously deleted; an eligible sole live leaf has `vmeta` cleared and its metadata retired, promoting it back to the raw-head path. (`src/db.c:1322-1401`)

The callback unlocks the owner, releases the version's lifecycle reference, and leaves the FLAT section. (`src/db.c:1134-1141`, `src/db.c:1403-1405`)

### Non-FLAT implementation gap

Physical node key DBs receive `KVSTORE_FLAT` only when `shared_node_dbs` is true, and `shared_node_dbs` is set only when workers per node is greater than one. (`src/server.c:5561-5580`, `src/server.c:6117-6121`)

`kvstoreFlatRetireVersionPrune` enqueues nothing when `flatCurrent(kvs)` is NULL, and the grace callback is reached only through FLAT retire-payload dispatch. (`src/kvstore.c:77-94`, `src/flatstore.c:43-51`)

On a non-FLAT versioned overwrite, metadata is constructed with `version_prev = old` and may inherit `old` as its committed cursor, but the non-FLAT tail still defers, asynchronously frees, or decrements `old`; the `!version_seq` preservation condition exists only in the FLAT arm. (`src/db.c:469-501`, `src/db.c:856-861`, `src/db.c:904-917`)

Consequently, in non-FLAT storage the code neither schedules the prune/promotion callback nor guarantees that a versioned predecessor referenced by the new metadata remains alive. (`src/db.c:856-861`, `src/db.c:904-917`, `src/kvstore.c:91-94`)

For an attached successful version in that mode, PRUNE does not select the detached release-after-unlock arm, the FLAT enqueue wrapper does nothing, and no callback reaches `tomoAtomicLifecycleRelease`; that lifecycle reference therefore has no release on this code path. (`src/server.c:10022-10029`, `src/db.c:1089-1105`, `src/kvstore.c:91-94`, `src/db.c:1134-1141`)

The configuration apply callback allocates lifecycle state when enabling and wakes waiters, but it performs no FLAT-storage validation; both atomic configuration entries remain accepted independently of storage mode. (`src/config.c:3141-3149`, `src/config.c:3183-3184`)

## Atomic-window behavior

A refused finite-window command is linked into its IO owner's `clients_atomic_window_parked` list and marked with both `CLIENT_ATOMIC_WINDOW_STALLED` and `CLIENT_PIPELINE_STALLED`. (`src/server.c:497-515`, `src/server.h:449-451`)

The owning event loop's retry walk first checks whether any waiters exist, then considers the current atomic knob/window, relaxed-loads `tomo_atomic_inflight`, sequentially-consistent-loads the cutover gate, removes an admissible client, clears both flags, and calls `processInputBuffer`. (`src/server.c:547-585`)

The walk runs in a later event-loop frame; a command may park again if another producer consumes the opened slot first. (`src/server.c:547-585`)

Changing the atomic configuration ensures lifecycle storage when enabling and wakes all producer event loops when a disable, an increased window, or window zero may make parked commands admissible. (`src/config.c:3141-3149`, `src/server.c:452-455`)

Window zero is unlimited but still counted in `tomo_atomic_inflight`; a finite window uses the counter itself as the CAS word and does not perform a separate load-then-increment. (`src/server.c:457-476`)

## Enforced invariants

1. Registration precedes the first owner publication and reserves exactly the group's expected number of connection-order slots. (`src/server.c:9914-9957`, `src/server.c:12702-12705`)
2. Each recorded install has an index below `version_install_expected`, an uncommitted sequence, a valid current owner, and a matching `csMsetInstall` record. (`src/server.c:11432-11451`)
3. A successful group draws a nonzero ticket only after `mset_install_count == version_install_expected`; an abort or MSETNX conflict draws no ticket. (`src/server.c:10293-10311`)
4. Per-connection ticket processing cannot pass an incomplete FIFO head, even when later groups complete first. (`src/server.c:10272-10287`, `src/server.c:10349-10361`)
5. Every successful group's STAMP jobs are queued before its `commit_seq` release, and every PRUNE job is queued after that release. (`src/server.c:10312-10333`, `src/server.c:10363-10383`)
6. STAMP, PRUNE, and CANCEL mutations run under the target worker's lock, and normal owner work drains pending owner operations first. (`src/server.c:9983-10046`, `src/server.c:21889-21893`, `src/server.c:21994-22004`)
7. The committed cursor is ordered by descending `(version_seq, version_order)`, even when owner-lane arrival order differs from ticket order. (`src/db.c:971-1009`)
8. A non-own committed read never accepts a metadata version above its snapshot; an own reader may select its own uncommitted version or its own stamped version above the snapshot. (`src/server.c:10133-10147`, `src/server.c:10242-10256`)
9. A selected tombstone is logical absence; atomic physical deletion occurs only in the prune callback after the tombstone becomes the eligible sole committed value. (`src/server.c:10144-10147`, `src/server.c:10255-10256`, `src/db.c:1345-1372`)
10. STAMP consumes the first of two owner-op references, PRUNE consumes the second, and CANCEL consumes its sole reference; assertions check the expected pre-decrement counts. (`src/server.c:10006-10035`)
11. Each installed version acquires an owner/bucket lifecycle reference before the install job can retire; FLAT prune completion or detached owner-op completion releases it only after owner-affine mutation has finished. (`src/server.c:367-397`, `src/server.c:11444-11448`, `src/server.c:10041-10046`, `src/db.c:1134-1141`)
12. A finite admission window increments only by a successful CAS below the bound, while window zero never refuses but still participates in census and teardown. (`src/server.c:457-476`, `src/server.c:15306-15324`)

The predecessor-lifetime and prune invariants in items 7, 9, and 11 are implemented end-to-end only for FLAT storage because the non-FLAT paths described above do not preserve or retire the bag through the version-prune callback. (`src/db.c:904-917`, `src/kvstore.c:91-94`, `src/flatstore.c:43-51`)

## Code/comment discrepancies and inactive remnants

### The old own-read HOLD path is not active

Comments and fields still name `csMsetHoldOwnRead`, `csMsetReadIntersects`, `csKeysCollide`, exact written-key vectors, publishing records, and `ownread_*` counters. (`src/server.c:724-756`, `src/server.h:1651-1697`, `src/server.c:9839-9871`, `src/server.c:12494-12511`)

The current code explicitly says the exact-key HOLD walk is gone, and the executable read path is `csMsetOwnVersionAt` followed by `kvobjVersionAt`. (`src/server.c:10101-10107`, `src/server.c:10133-10256`)

The `ownread_*` values are aggregated and emitted by INFO, but the shown declarations/aggregation are not part of the resolver and the resolver contains no counter updates or wait. (`src/server.c:724-756`, `src/server.c:19194-19196`, `src/server.c:19272-19282`, `src/server.c:10133-10256`)

The retained `mset_read_waiting` field is initialized, but the completion-side reference to it describes a deleted hold; the active resolver does not test the field. (`src/server.h:1846-1850`, `src/networking.c:663-671`, `src/server.c:10405-10412`, `src/server.c:10133-10256`)

`csMsetPopComplete` still copies a departing group's key hashes into `csMsetPub`, but the active publication loop directly decrements `mset_pending_count` instead of invoking `csMsetPubRetire`; the retire helper remains separately defined. (`src/server.c:9873-9912`, `src/server.c:10272-10286`, `src/server.c:10395-10400`)

Accordingly, neither the publishing-record ring nor the hash-vector comments describe the active own-read algorithm; origin identity and the two version chains do. (`src/server.c:10101-10256`)

### Numeric `install_order` is not the resolver order

Registration reserves a connection-global range and installation writes `vmeta->install_order = base + ii`, but the own-uncommitted resolver does not read that field. (`src/server.c:9946-9950`, `src/server.c:11432-11448`, `src/server.c:10133-10147`)

The committed insertion code compares `version_order`, despite nearby comments describing a `(seq, install_order)` ordering. (`src/db.c:971-991`)

The implemented ordering is therefore physical `version_prev` order for the own-uncommitted scan and `(version_seq, version_order)` for committed history. (`src/server.c:10133-10147`, `src/db.c:976-1009`)

### The scope is broader than the knob comment

The server field comment describes “epoch-versioned MSET/MGET atomicity,” but admission also covers DEL/UNLINK, MSETNX, and the PORTALL families listed above. (`src/server.h:4114-4115`, `src/server.c:588-612`, `src/server.c:8350-8365`)

### There is not one frontier load for every dispatch

The code performs the dispatch-time acquire load only in the enabled cross-routed read/source-read branch, while raw single-owner reads return before a frontier draw. (`src/server.c:8465-8471`, `src/db.c:366-371`)

### MSETNX does not use tombstones

The implemented MSETNX path installs requested values marked as reservations and later stamps or cancels them; tombstones are used by DEL/UNLINK, empty stores, and RENAME source deletion. (`src/server.c:11477-11505`, `src/server.c:10294-10329`, `src/server.c:11509-11539`, `src/server.c:11321-11337`)

## File:line map

| Area | Primary implementation |
| --- | --- |
| Config defaults and live apply | `src/config.c:3141-3149`, `src/config.c:3182-3184` |
| Owner-op enums, version states, and every `tomoVerMeta` field | `src/object.h:105-180` |
| Version pointer/link acquire-release helpers | `src/object.h:219-261` |
| Per-client FIFO/latch/window state | `src/server.h:1651-1697`, `src/server.h:1783-1795`, `src/server.h:1839-1858` |
| `csMsetInstall` and versioned `csGroup` fields | `src/server.h:2102-2151` |
| Global frontier/controller and admission/lifecycle counters | `src/server.c:280-342` |
| Snapshot helpers and window reservation/parking | `src/server.c:427-585` |
| Atomic command-shape selection | `src/server.c:588-647`, `src/server.c:8344-8387` |
| Dispatch snapshot draw | `src/server.c:8450-8471` |
| Commit lock, per-client registration/FIFO, owner lane, resolver, and commit publication | `src/server.c:9790-10413` |
| Command registry coverage | `src/server.c:10784-10921` |
| Version installs, tombstones, MSETNX reservations, and MSET values | `src/server.c:11282-11359`, `src/server.c:11432-11599` |
| MSETNX owner-ordered waves | `src/server.c:12710-12799` |
| Gather group construction | `src/server.c:13511-13740` |
| Two-hop/RENAME group construction | `src/server.c:14320-14519` |
| Terminal group teardown/window retirement | `src/server.c:15294-15328` |
| Owner execution ordering | `src/server.c:21889-22004`, `src/server.c:22144-22199` |
| Read lookup integration and metadata construction | `src/db.c:361-397`, `src/db.c:469-501` |
| Versioned physical prepend and predecessor lifetime | `src/db.c:761-920` |
| STAMP, CANCEL, single-version license, and PRUNE arm | `src/db.c:922-1105` |
| Detached bags and prune-after-grace callback | `src/db.c:1108-1405` |
| Versioned set entry points | `src/db.c:1560-1632` |
| FLAT prune callback encoding/dispatch | `src/flatstore.c:25-68`, `src/flatstore.c:176-196` |
| FLAT wrapper's non-FLAT no-op condition | `src/kvstore.c:77-97` |

## Mechanisms

- [Commit-sequence ordering](mechanisms/algorithms/commit-seq-ordering.md)
- [Version resolution](mechanisms/algorithms/version-resolve.md)
- [Own-read widening](mechanisms/algorithms/own-read-widening.md)
- [Install-commit protocol](mechanisms/algorithms/install-commit-protocol.md)
- [DEL tombstone versions](mechanisms/algorithms/del-tombstone-versions.md)
- [Bloom signature](mechanisms/algorithms/bloom-signature.md)
- [Atomic window](mechanisms/algorithms/atomic-window.md)
- [Version bag](mechanisms/buffers/version-bag.md)
