# Atomic write-path audit

Baseline audited: `81eaf79b1` (`atomic: instrument remaining read and write costs`)

Target workload: pure eight-key MSET, warm 10k keyspace, static io4/ex4, 200
connections, pipeline 32, FLAT shared-node store. No measurements in this report
were rerun. The supplied counters and perf results are treated as facts.

## Verdict

There is no credible hidden 2,900-instruction install or commit-lock item. The
write tax is the sum of repeated maintenance machinery:

- every installed key creates two owner-lane jobs (STAMP and PRUNE);
- every key is found in the FLAT table again at STAMP and again after prune
  grace;
- every key gets a prune callback with its own flat-section handshake and
  worker lock, followed by three short but separate walks;
- every key creates three retire records versus one physical record on an
  ordinary FLAT overwrite;
- group publication and admission add several smaller RMW/lock/list passes;
- with the finite window binding, each group retirement can fan out eventfd
  writes to every IO slot; and
- the current cost census itself adds owner-local bookkeeping on all of these
  paths.

The ranked midpoint budget below is deliberately constrained to the measured
approximately 2,900 extra retired instructions per written key. It is an
allocation of that known total, not a claim that source inspection can measure
individual functions. The ranges are falsifiable engineering estimates. A
conditional row that measures near zero means its budget belongs in the other
distributed rows; it does not change the measured total.

The table counts **retired instructions only**. Cache-line transfer and miss
stall are called out separately and are not converted into instructions. That
keeps the ledger consistent with the measured 74% instruction / 26% lost-IPC
split.

## Ranked instruction ledger

| Rank | Step | Estimated extra instructions / written key | Atomic-only or shared with ordinary FLAT | Scale today | Removable? |
|---:|---|---:|---|---|---|
| 1 | Extra retire lifecycle: two additional retire records, special-payload dispatch, node recycle, metadata retirement/free | **330** (220-440) | Atomic-only delta. Ordinary overwrite has one physical retire; atomic measured three retires/key. | Per key, across two grace stages | Partly. Intrusive/reused records or a combined stage need a lifetime design. QSBR polling itself is not the target. |
| 2 | Two `csStampPush` producer operations: queue staging plus `stamp_pending`, tail publication, and handoff advertisement | **320** (220-420) | Atomic-only | Twice per key | PRUNE can potentially ride the STAMP completion. Merely batching pushes by owner is already falsified. |
| 3 | Fixed prune-callback work: flat-section seq-cst enter/exit, resize check, worker publication lock, current-head lookup, branch/assert scaffold, cursor publication, promotion bookkeeping | **300** (190-410) before this patch | Atomic-only | Per key | Yes in pieces. Reuse the lookup hash; enter/lock once per reclaimed owner batch; shard observability. |
| 4 | Two `csStampDrain` entry bodies: pop/decode, kind dispatch, two `owner_ops_pending` RMWs, op clearing, PRUNE arming | **280** (190-380) | Atomic-only | Twice per key | Mostly only by deleting/fusing PRUNE. The per-version lifetime pin itself is semantic. |
| 5 | Commit/R1 publication excluding queue pushes: pending-FIFO lock/unlink, publishing-record hash copy, ticket draw, two install-array walks, commit-seq store, reply publish, pending-record retirement | **280** (190-380) | Atomic-only | Fixed per group plus two per-key loops | Some per-key work disappears with PRUNE piggyback. The global ordering edges are semantic. |
| 6 | `tomoApplyVersionStamp`: current-head lookup and descending committed-cursor insertion/update | **270** (160-380) before this patch | Atomic-only | Per key | Hash reuse is unambiguous and implemented. Removing the ordered insertion needs an inversion counter first. |
| 7 | Finite-window retirement wake fanout: up to four `eventfd` `write(2)` calls per eight-key group, plus notifier drain work | **240** (0-450) | Atomic-only and conditional on waiters | Per group, fanned to every IO slot | Likely high value if active. Coalesce by armed edge/batch, but a prior implementation was reverted and must not be restored without its liveness falsifier. |
| 8 | Prune loop bodies: physical-bag, committed-chain, and survivor-census walks | **230** (160-320) | Atomic-only | 5.1 measured steps per key in three walks | Partly. Physical unlink and census traverse the same linkage and may be fused; committed order is a distinct linkage. |
| 9 | Auxiliary worker-slice framework induced by owner jobs: flat-section handshake, loop heartbeat, sparse-summary harvest, clocks/accounting, and an otherwise empty normal-lane scan | **180** (0-300) | Framework is shared; extra owner-only activations are atomic-induced | Per owner-drain pass | Conditional. Count stamp-only slices before changing it. Under full normal backlog this can be almost fully piggybacked already. |
| 10 | Admission, registration, and teardown: inflight reserve/retire RMWs, per-client pending lock/list/count, drain latch, fence, waiter check | **150** (90-220) | Atomic-only | Mostly per group (amortized by eight) | Limited. The finite bound and R1 FIFO are semantic; wake policy is separable. |
| 11 | Current measurement census: allocation classification, retire/walk/drain tallies, and sampled-phase gates | **120** (80-160) | Asymmetric: OFF records one raw allocation; ON records kvobj + vmeta and all atomic phases | Mostly per key | Yes after the investigation, or behind a build-time diagnostic gate. Kept for now because it supplies the falsifiers. |
| 12 | QSBR close/readiness machinery attributable to extra retire traffic | **100** (50-160) | Shared engine, amplified by atomic's 3x retire records | Per reclaim pass/batch | Low priority and already refuted as the bulk: 8.9 to 83 objects/batch and 303 to 119 ns/pass produced only about +1% throughput. |
| 13 | `csMsetRecordInstall`: contended `mset_install_count` RMW plus vmeta/install-array stores | **65** (35-90) | Atomic-only | Per key | Yes with a deterministic per-sub/original-position slot plan; duplicate-key order must be preserved. |
| 14 | Atomic group additions: signature OR, full-hash vector stores, 192 extra inline bytes zeroed for eight installs/hashes, allocation-stat counters | **35** (20-60) | Shared group allocation/dispatch plus atomic-only fields | Per key, mostly one group allocation | Little. The exact hashes are required for the own-read gate and reuse the routing hash. |
| 15 | Version installation itself, including the separate vmeta allocation | **0** (-100 to +50) net | Different twin of the shared SET path | Per key | Not a positive target. It measured 50.8 ns versus ordinary's 62.8 ns. |
| 16 | Classification, ordinary coalesced dispatch, key/value prefetch, encoding, key notifications, dirty accounting, CDB reply, common sub/group destruction | **0** net | Shared | Per group/key | No atomic redundancy found. |

Midpoint sum for ranks 1-14: **2,900 instructions/key**. Ranks 15-16
are intentionally assigned no positive tax because direct measurement or code
identity rules them out.

Estimate anchors used in the ranges:

- an uncontended atomic RMW is budgeted at 20-40 instructions; contention adds
  cache/IPC stall, not more retired instructions in this ledger;
- a small jemalloc allocation/free lifetime is 100-200 instructions, but the
  vmeta allocation is already inside the measured net-cheaper install and is
  not charged a second time;
- group-fixed work is divided by eight;
- the measured 5.1 prune steps are budgeted at roughly 30-50 instructions per
  branch-heavy link step; and
- a roughly four-cycle L1 hit is not translated into four instructions, while
  an LLC/remote miss is charged only to the separate IPC discussion.

## End-to-end audit

### 1. Classification and admission

`processCommand()` classifies the cross-shard row before atomic admission and
reuses `atomic_csp` for dispatch. Atomic OFF performs the same classification
later. There is no second classifier pass to remove.

Finite admission adds one CAS loop on `tomo_atomic_inflight` per group. At the
default window of 512, refusal enrolls a waiter. This is group-scaled and small
in retired instructions, although the shared admission line can add IPC loss.

Pure MSET does **not** take the cross-shard read snapshot/QSBR pin. That arm is
guarded by `TOMO_R_ATOMIC_READ`; the MSET row is a write-only bag operation.
Snapshot pinning therefore does not belong in the pure-write ledger.

### 2. Group construction and dispatch

The coalesced routing pass hashes every key in both modes. Atomic mode only ORs
the signature and stores that already-computed hash in `g->key_h`; it does not
rehash for the R1 exact test. This confirms the supplied refutation of the
`csOwnReadSignature` / `csKeysCollide` theory.

For MSET8, atomic adds eight 16-byte `csMsetInstall` slots and eight 8-byte full
hashes: 192 bytes. They are carved from the same `csGroup` allocation, so this
is extra zero/cache footprint, not two allocator calls. The connection's
publishing ring is a one-time lazy allocation, 32 records x 152 bytes at the
target pipeline depth; it is not a steady per-operation allocation.

`csMsetRegister()` adds a pending-list lock, link updates, and a pending-count
RMW once per group. The publishing-record copy later writes eight hashes per
group. Those hashes cannot simply be omitted: they close the completed-but-not-
yet-published window that previously caused almost all remaining own-read
holds.

Normal sub creation, per-owner coalescing, argv construction, queue dispatch,
worker locking, and the sub-completion `pending` RMW exist in the ordinary MSET
path too.

### 3. Per-key install

The ordinary and atomic MSET loops have the same prefetch waves, hash carry,
encoding, notification, and dirty accounting. FLAT disables the ordinary
in-place overwrite, so both paths allocate a replacement kvobj.

Atomic adds a separately allocated `tomoVerMeta`, currently about a 128-byte
small allocation, initializes its cursor/state, and links the prior head. That
gross allocator work is real, but it cannot be booked again as a positive
install tax: the whole measured version install is already 12 ns faster than
the ordinary install. The ordinary arm immediately queues the replaced raw
object; atomic defers its retirement through later phases. Any vmeta embedding
or slab proposal must therefore prove an end-to-end instruction reduction; the
allocation count alone is not evidence.

Immediately after the measured install, `csMsetRecordInstall()` performs a
shared fetch-add for every key, even though same-key duplicates necessarily run
in argv order on one owner. A dispatch-assigned record index could turn that
into owner-private stores, but MSET's current coalesced sub argv does not carry
original positions. Adding that map/range and proving duplicate ordering is a
design change, not an audit-only edit.

### 4. Commit publication

The last sub release-stores `mset_complete`, competes for a per-client drain
latch, and enters the global commit lock. For each ready group:

1. it removes the group from the client's R1 FIFO and copies its key set into
   the publishing ring;
2. it draws one sequence ticket;
3. it walks every install, initializes two embedded owner operations and pushes
   STAMP;
4. it release-publishes `commit_seq`;
5. it walks every install again and pushes PRUNE;
6. it publishes the reply slot and retires the publishing record/pending count.

The fixed ordering work is per group. The two walks and sixteen owner pushes
are per key. Owner-run batching already reduced pushes/group from 16 to 7.2
without moving throughput, so this report does not propose that point fix
again. Deleting the semantic second message is different: PRUNE contains no new
key identity or sequence information; it tells the same owner to arm retirement
after the STAMP's sequence becomes globally committed. Piggybacking therefore
has a plausible 170-260 instruction/key saving, but it needs an owner-local
early-STAMP deferral for the race where STAMP drains before `commit_seq` is
published. Repository commit `2ccae7c3a` contains such a design; it is not
merged here because liveness under full lanes, migration, cancel, and dormant
owners is a design verdict, not an obvious local deletion.

### 5. Stamp push and drain

Each `csStampPush()` publishes one entry with a `stamp_pending` RMW, queue-tail
release store, and summary advertisement. Each key does that twice. Those
shared producer/consumer lines are also strong candidates for the measured IPC
loss, but their cache-bounce latency is not included in the instruction column.

`csStampDrain()` decodes two entries per committed key and performs two
`owner_ops_pending` fetch-subs. STAMP re-finds the current physical head, loads
the committed cursor, and inserts by descending `(seq, version_order)`. The
lookup is required because newer installs may have changed the head, and the
ordered insertion is required if stamps can arrive out of ticket order.

The existing `stamp_apply_walk` counter can falsify simplification of that
ordered insertion. Add a separate `committed_previous != NULL` counter before
replacing it with a head-only operation; total walk depth alone does not prove
that no out-of-order insertion occurred.

### 6. Retirement, prune, and reclaim

The measured structure is exact: one prune callback/install, 3 retire records
per key, and 5.1 prune steps/key split across three traversals. The important
distinction is:

- grace polling was cheap and its batching experiment is refuted;
- retire **payload work** still exists: list/node traffic, callback dispatch,
  a live-table maintenance lookup, unlink/chain repair, another physical grace,
  vmeta retirement, and destruction.

`tomoVersionPruneAfterGrace()` is called once per key. Each call separately
enters the FLAT section with seq-cst ordering and takes the owner's publication
lock, even when many prune anchors are being released from one reclaimed batch.
That is a clear per-key-to-per-batch asymmetry. A batch wrapper could enter and
lock once, process consecutive prune payloads for that owner, then exit once.
Expected saving: about 60-120 instructions/key plus less lock-line traffic. It
needs careful review against HFE's multi-worker lock protocol and callback-
generated retirement, so it is report-only.

The physical-bag walk unlinks eligible members. The committed-chain walk repairs
a different ordering and cannot be blindly merged. The final census walks the
physical linkage a second time. Folding survivor counts into the first physical
walk should remove about 1.03 measured steps/key, but promotion decisions must
be based on the final survivor set. Estimate: 40-90 instructions/key; falsifier
is unchanged retirement/promotion counts and a one-walk reduction in the census
counter.

The nearly one vmeta retirement/key also revealed an observability-only shared
RMW: `tomo_atomic_promotions`. That was unambiguously redundant synchronization
and is sharded by this patch.

### 7. Teardown and wake

Common sub destruction, reply creation, command statistics, inline-array frees,
and the final group free are shared. Atomic adds the inflight decrement, a
seq-cst fence, and a waiter test once per group.

If any waiter exists, current teardown calls `tomoAtomicWakeAll()`, which calls
`triggerEventNotifier()` for every IO-capable slot. On Linux that is one
`write(2)` per slot. With io4 and MSET8, the upper rate is 0.5 eventfd writes per
written key, before counting the event-loop reads. Repository commit
`de691bbf6` recorded 2.5-3.0 million such syscalls/s at about 629k group
retires/s, then `91ac1c600` reverted the coalescing change without recording a
replacement rationale. The cost is therefore plausible but conditional.

The falsifier is direct: count retire-side notifier writes and groups retiring
while `tomo_atomic_waiters != 0`. If writes/group is near zero, rank 7 is dead.
If it is near the IO-slot count, an edge-armed per-slot wake should reduce it
toward one write per actual sleep episode. Any retry must preserve the P2
decrement/waiter missed-wakeup proof; this audit does not reapply the reverted
patch.

## Per-key / per-group / per-batch asymmetries

| Current work | Better scale | Estimated instruction opportunity | Status |
|---|---|---:|---|
| One PRUNE queue entry and drain entry per key, after a STAMP for the same vmeta | Fold into STAMP; defer locally only if commit publication has not caught up | 170-260/key | Best structural candidate; design/liveness proof required |
| One flat-section entry and worker-lock pair per prune callback | One pair per reclaimed owner batch | 60-120/key | Report-only; lock protocol review required |
| Physical-bag walk followed by physical-bag census | One physical walk carrying survivor counts | 40-90/key | Report-only |
| One shared install-count RMW per key | Dispatch-reserved slot/range per sub, one group completion count | 25-60/key plus IPC | Report-only; preserve duplicate-key order |
| One group retirement wakes every IO slot | One armed edge per slot/sleep episode | 0 or 150-350/key | Measure first; prior implementation reverted |
| Cost-census allocation/walk/retire updates per key | Build-time diagnostic off, or local batching | 80-140/key | Intentionally retained for current campaign |
| One QSBR close per short retire wave | Larger retire batch | Small after measured refutation | Rejected: structural counters moved, throughput did not |
| One owner-lane publication per key | One publication per owner run | Already tested | Rejected: 16 to 7.2 pushes/group, zero throughput movement |

## Unambiguous changes made

### Reuse the maintenance lookup hash

Before this patch, both `tomoApplyVersionStamp()` and
`tomoVersionPruneAfterGrace()` did this for the same key inside one phase:

1. `getKeySlot(key)` evaluated `xxh64` to obtain the ownership bucket;
2. `kvstoreDictFindLink()` evaluated `xxh64` again for the FLAT probe.

The patch evaluates the full hash once and passes it to the new
`kvstoreFlatFindLinkByHash()` helper. It removes one short-key xxh64 evaluation
from STAMP and one from PRUNE: estimated **60-110 instructions/key** total.

This is separate from the already-refuted own-read hash theory. No code in
`csOwnReadSignature()` or `csKeysCollide()` changed; that path already retains
and reuses hashes correctly.

### Shard the promotion statistic

Promotion previously performed a relaxed shared atomic fetch-add nearly once
per key solely for INFO. It now increments the existing cache-line-aligned,
owner-written `tomoAtomicCostStat` slot and INFO folds the slots. Estimated
saving: **20-40 instructions per promotion**, or about **19-39 instructions per
written key** at the measured 0.964 vmeta retirements/key, plus removal of one
globally bouncing cache line.

### Delete a duplicate install-order field

`csMsetInstall.install_order` was always assigned the array index and only read
by assertions that it equaled that same index. The semantic tie-break remains
in `vmeta->version_order`. The field and its redundant store/load were removed;
the struct remains 16 bytes because of pointer alignment, so the estimate is
only **3-8 instructions/key**, with no claimed footprint saving.

Combined expected saving: approximately **80-160 instructions/key**, or
**640-1,280 instructions per MSET8 operation**. This is intentionally modest:
it attacks three proven redundancies, not the whole distributed tax.

### Falsifier for this patch

On matched ON/OFF runs:

- atomic-ON instructions/op should fall by roughly 640-1,280 for MSET8;
- atomic-OFF instructions/op should not move;
- installs, STAMP/PRUNE drain entries, prune callbacks, all three retire counts,
  all three prune walk counts, and committed results must be unchanged; and
- `tomokv_atomic_promotions` must continue to track
  `tomokv_atomic_retire_vmeta` (allowing only an INFO sampling boundary).

If ON instructions/op falls by less than about 400, the hash instruction
estimate is wrong and the patch is not a material win. Throughput is not the
verdict on this box.

## Considered and rejected

- **Commit critical-section batching:** rejected by its own counters: owner
  publications/group fell 16 to 7.2 and throughput moved zero. It remains in
  the inventory but is not recommended again.
- **Version install:** rejected by direct timing, 50.8 ns atomic versus 62.8 ns
  ordinary. The ordinary FLAT overwrite also allocates a replacement kvobj.
- **Own-read hash recomputation:** rejected by inspection. `rk->h[]` is filled
  once and consumed by `csKeysCollide()`. The implemented hash reuse is in two
  write-maintenance lookups, not that read path.
- **QSBR polling/close as the bulk:** rejected by 8.9 to 83 objects/batch, 303
  to 119 ns/pass, and only about +1% throughput. Do not mistake three retire
  payloads/key for expensive grace polling.
- **Shorten version chains for mixed reads:** rejected by the measured mean
  resolve depth of 1.03. The mixed-read cost is the fixed resolver and cache
  invalidation, not a long chain.
- **Drop the written-key hash vector/publishing record:** rejected. They are the
  exact R1 proof during linked and detached publication windows; removing them
  restores conservative holds.
- **Cache a table link or head pointer from install until STAMP/PRUNE:** rejected.
  Newer same-key installs and FLAT resize can invalidate which head/link is
  authoritative; maintenance must re-find it under the owner protocol.
- **Assume every STAMP is a new committed head:** not proven. Instrument
  non-head insertions first; migration and multi-producer arrival are the
  relevant falsifiers.
- **Naively embed vmeta in kvobj:** not self-contained. Promotion deliberately
  detaches/frees metadata while retaining the raw kvobj; embedding either keeps
  the footprint forever or needs a different promotion representation.
- **Remove install/op clearing stores:** they appear semantically dead after
  publication, but currently act as exactly-once tripwires in teardown and
  duplicate-consumption failures. Their single-digit instruction value is not
  worth weakening those assertions in this audit.

## Cache/IPC ledger

The instruction table does not charge cache misses as instructions. The main
atomic-only invalidation/pointer-chase sources are:

- `mset_install_count`, `stamp_pending`, queue tail/summary, commit control, and
  finite-window counters moving between producer and owner cores;
- one separately allocated vmeta per key and its committed-head pointer;
- STAMP and PRUNE re-probing a live FLAT slot and dereferencing a head a writer
  is replacing;
- prune's physical and committed linkages; and
- the former global promotion statistic, removed here.

An L1 hit or atomic operation has an instruction cost represented in the table;
a remote-line miss adds stall and lowers IPC. The supplied 250 extra misses/key
and 26% lost-IPC share already measure that second effect. No candidate in this
report claims those miss cycles as retired-instruction savings.

## Verification performed

- Walked classification, group sizing/build, owner dispatch, ordinary and
  versioned MSET loops, install recording, commit publication, STAMP/PRUNE
  producer and consumer paths, version pruning, both grace stages, reassembly,
  admission retirement, and wake delivery.
- Confirmed every removed symbol/reference with repository-wide search.
- `git diff --check` passes.
- Per the hard constraint, no compiler, build, server, test, or benchmark was
  run. Runtime validation belongs to the owner of the measurement box.
