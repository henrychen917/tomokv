# TomoKV coherent refactor

This branch is a single design pass over transport, prefetch, scheduling, ownership publication,
allocation, and deletion-audited cleanup. It is intentionally not a merge of every supplied patch.
Where an input disagreed with the live source, the source won and the disagreement is recorded
below.

## Status and staged history

The implementation is based on `7880fd0eb` and is split into buildable commits:

| Commit | Coherent stage |
|---|---|
| `e15b53463` | Bound global topology and replace O(worker-count) producer publication with an exact dirty-worker set. |
| `b3316cb20` | Close worker-start, queue publication, runtime replica-role, and role-transfer races. |
| `dd0eef77a` | Embed pending-execution list membership, move cross-shard argv scratch onto group storage, and remove audited sampler/eviction scaffolding. |
| `8dd92da48` | Close role activation, retirement, rollback, FLAT orphan, and flush-sentinel gaps. |
| `e92ae0fa2` | Preserve listener configuration and owner-publication semantics across role changes. |
| `1f58186a8` | Publish replica/client counts and reject unsafe live listener mutation. |
| `6fd33680d` | Implement one EX-prefetch pipeline for DICT and FLATSTORE. |
| `365c83972` | Add consuming cross-client IO ingress and reply prefetch. |
| `818b7ddeb` | Add dependency-safe, closed-batch cost scheduling and repair the IO fired-event consumer after adversarial review. |
| `e5dd55cc1` | Guard keyspace-dict lifetime, refuse unsafe HOTKEYS sessions, and apply only corrected SAFE-TO-DELETE cleanup. |
| `5067636a4` | Remove boot-dominated cluster paths and constant polymorphic-role guards from the IO poll path. |
| `8782313a4` | Make BITCOUNT prefetch engagement and enabled-but-no-issue execution independently observable. |

Every executable stage completed `make -j4`. The final verification and exact tree state are recorded
at the end of this file. As required, no server, test, or benchmark was run.

`inputs/designs/SCALE_AUDIT.md` is not present in the supplied tree. The 96-core conclusions here
come from the live constants, structure layouts, loop bounds, and the other supplied evidence; they
are not attributed to a document that was unavailable.

## Settled architecture

The request path is:

```text
IO-owned fired-event wave
  -> client fake ring
  -> producer-private SPSC staging + sparse release publication
  -> one worker-owned, already-popped batch
  -> dependency-safe cost lanes
  -> storage-order prefetch
  -> authoritative command lookup/execute
  -> exact CDB completion
  -> IO-owned grouped reply drain
```

The important boundary is the already-popped worker batch. Scheduling and EX prefetch operate only
inside that bounded, owner-local prefix. They do not add another admission queue, a foreign owner,
a timer, or a persistent dependency table.

### Transport and topology

The global capacities are now explicit: 32 IO identities, 64 EX workers, and 96 total Tomo threads.
Startup multiplies per-node configuration in a wide type and rejects any global total outside those
bounds before indexing fixed arrays. Stock Redis `io-threads > 1` is also rejected: this fork owns
its own connection/event-loop pool and cannot safely run the upstream pool beside it.

Each IO producer stages ordinary jobs in its private SPSC rings. A TLS `uint64_t` records exactly
which workers have unpublished staged jobs. `flushExQueues()` uses `ctz` to publish one
release-store per touched worker instead of scanning every worker. Cross-shard subrequests use the
same rings but publish immediately after every successful push. If any ring is full, all previously
touched ordinary rings are published before retrying the full ring. Every live push site retries;
the audit's possible ignored-return/lost-command premise was stale, but publication before
backpressure was still needed to prevent self-inflicted stalls. Queue exhaustion remains visible
as a retry/backpressure counter.

The worker still rotates over producer rings for fairness, pops at most 16 entries from one ring,
and adaptively spins before yielding. `head` is a pop frontier, not a completion frontier, so role
retirement and migration use the consumer-published `retired == tail` proof. Reply completion uses
the fake's captured CDB. The IO owner acquire-loads only the exact buses named by its ready prefix;
it no longer OR-scans every bus.

Role conversion now has explicit startup adoption, listener admission, cancellation/rollback, live
count, flush, and FLAT-reclamation handoffs. Custom IO listeners bind one configured plaintext IPv4
address, never an accidental wildcard. A TLS-only, IPv6-only, or zero-plaintext-port custom-listener
shape is refused rather than silently opening a different surface. Runtime `bind`, plaintext port,
and related listener mutation is rejected while custom listeners exist.

At exactly IO 32 + EX 64, there is no growth IO slot. Auto mode logs that fact, holds the configured
split, and disables controller-only signals. The configuration is memory-safe and bounded; it is not
an actuating auto configuration.

### EX prefetch

`tomokv-prefetch-ex` is checked once after a nonempty pop. With level zero, the noinline pipeline,
scratch arrays, stage counters, and hint instructions are not entered.

DICT batches use a real staged dependency chain:

```text
fake/client -> argv -> key object -> key bytes -> hash -> bucket/entry -> kvobj -> value data
```

The KVOBJ and VALDATA stages are separate. VALDATA is issued only after an exact-key qualification;
the staged pointer is never accepted as a lookup result.

FLATSTORE batches no longer retire at `kvstoreGetDict() == NULL`. They stage the current table and
home slot, use the 15-bit tag to qualify a candidate shell, verify the exact key, and only then hint
the value. Ordinary single-key operations and MGET share this grouped flat probe. FLAT MSET uses
8-entry subwaves over scratch sized for 32 operands. BITCOUNT selects a sequential
payload-prefetch loop once before its scan; its hint count scales with the selected byte range.
The real command path always re-probes authoritatively.

Level 2 enables next-op look-ahead with distance `max(1, n/4)`, so the index is reachable for a
nontrivial DICT batch. It reacquires the current DICT dictionary and exponent at issue time; the
FLAT pipeline already stages the current operation and does not run this next-op arm. The Tomo
keyspace constructor now rejects `KVSTORE_FREE_EMPTY_DICTS`; this turns the already-deliberate
persistent bucket-dict premise into a boot-time invariant.

Owner-local counters distinguish:

- pipeline entered, gated, and entered-but-issued-nothing;
- each actual metadata, dict, flat-slot, shell, value, bit-data, and next-op hint stage;
- eligible versus actually issued flat/value/next-op hints; and
- flat, MGET, MSET, and BITCOUNT invocations whose enabled pass issued no hint.

Periodic atomic snapshots make these counters readable by INFO without a foreign read of worker
state. The first enabled and first actually issuing pass are published immediately enough to avoid
a vacuous short run.

### IO prefetch

Ingress prefetch is an event consumer, not a same-client prefix walk. When level 2 or higher is
installed, the AE hook owns the fired array. It divides it into contiguous ranges of at most 16
fired entries, stages eligible clients across that range, and immediately executes the exact range
with the original generic or custom-IO callback/barrier order. It never pre-walks a whole poll and
then restarts from event zero. Typed file-event metadata prevents listener pipes, module fds, or
arbitrary callback data from being interpreted as a connection.

Reply prefetch uses a boundary sentinel in the owner-local pending-execution list. It gathers at
most 16 original nodes, stages real client/ring/fake/exact-CDB/output state, consumes that group,
and then continues after the boundary. Wakeups are deferred by stable client ID so a callback
cannot leave a raw client pointer live across a free.

Level 4 stages only a validated RAW reply payload. It validates the encoded block and RESP shape,
then follows the existing `bulkStrRef` reference already held by reply construction. The
prefetcher does not take another reference: the reply-held reference remains live until
send/teardown and worker-owned references return through freeback. The hint is not authoritative.

Ingress and reply stats have separate publication cadence and separate first-issuing publication.
They report selection/occupancy, each actual hint stage, partial/short/no-ready gates, and no-issue
passes. This distinguishes “enabled” from “enabled but no useful address was issued.”

### Cost scheduling

The scheduler deliberately uses two transient stable lanes over one already-popped SPSC prefix,
not two persistent worker admission queues. This is the central correctness choice.

The first policy is intentionally narrow:

| Command shape | Class |
|---|---|
| first-in-flight, exact `GET key` | short and promotable |
| exact `BITCOUNT key ...` | long |
| exact `SET key ...` | dependency-bearing neutral |
| later request from the same client | not promotable |
| multi-key, scatter group/subrequest, module/unknown, rewritten key, FLUSH, or migration sentinel | fence |

The IO owner stamps `CLIENT_TOMO_SCHED_HEAD` only when it proves the real client's ring was empty.
The worker never reads another owner's ring cursors. Runtime classification repeats the
`argv[1] == tomo_bkt_ptr` identity guard, so a rewrite or stale classification becomes a fence.

The worker first scans the batch for a HEAD short and a long. Only that mixed shape is an
opportunity. It then stable-partitions into:

1. eligible HEAD GETs whose 64-bit dependency bit is not blocked; and
2. everything else, in original order.

Every deferred request contributes `1 << (full_hash & 63)`. Unknown/control work contributes all
bits. Equal keys necessarily collide and therefore cannot pass; unrelated keys can collide only by
refusing a legal promotion. The two lanes are fully drained before the worker pops again.

The selected GET prefix executes and publishes its completion before the deferred lane. All fake
bookkeeping, argv release, load accounting, value observation, parent capture, and slot capture
occurs before the release RMW. No prefix fake or parent is dereferenced after publication. Same
parent masks are coalesced inside the prefix.

The starvation proof is structural: with `WORKER_POP_BATCH == 16`, the earliest deferred request can
be bypassed by at most the other 15 entries, then the deferred lane drains before refill. INFO
reports bound checks, nonvacuous checks, maximum observed bypass, and violations. A violation must
remain zero.

Auto mode samples one in 64 non-singleton batches while inactive. A sampled useful batch is really
scheduled; it is not shadow accounting. The worker remains active while useful and returns to
sampling after 256 inspected batches without a selected prefix.

Scheduling runs before EX prefetch so storage staging follows actual execution order. This differs
from the supplied scheduler patch, which partitioned after prefetch and would stage the old order.

There is no preemption, IPI, context switch, global queue, clock read, heap allocation, or sort in
this scheduler.

### Allocation and cleanup

The pending-execution list node is embedded in the real client, matching the existing pending-write
pattern. Enrollment/removal is pointer manipulation with no per-transition list-node allocation.

Cross-shard subrequest argv arrays use group-owned inline storage and spill only when the group
exceeds that bounded storage. The group owns both the storage decision and the free path.

The per-command arena was rejected. The supplied design added a fourth knob and could not close
escapes through replies, blocking state, propagation, containers, rewrites, and module APIs. An
object that can outlive the command cannot safely come from such an arena.

The cleanup stage removed only paths covered by a SAFE-TO-DELETE audit or a corrected follow-up:

- sampling and eviction-bucket scaffolding whose observables were separately preserved;
- unreachable dynamic module loading internals, while preserving the `loadmodule` parser, boot
  refusal, MODULE command entries, reply schemas, bundled Vector Sets, and unresolved-config error;
- six write-only/private fields and their orphan allocations; and
- fourteen uncalled private helpers;
- cluster-positive cron, before-sleep, startup, and geometry arms dominated by the retained
  `cluster-enabled yes` boot refusal; and
- a narrow audited set of `poly_threads == 1` guards on every IO poll, while retaining the
  legacy thread-main fallback code whose late rebase would touch newer role-activation logic.

No existing configuration name was removed. In particular, a configuration file containing
`loadmodule` still gets the fork's explicit unsupported-policy diagnostic rather than an unknown
directive, and the compatibility `maxmemory-clients`, strict-order, and retired hidden prefetch
batch parsers remain accepted with their documented refusal/no-op behavior.

HOTKEYS START is now explicitly unsupported. The supplied HOTKEYS patch moved some scratch to TLS
but left process-global heaps/counters/session reclamation racy, and worker commands bypass `call()`
so its results would still omit the normal keyed path. Refusing the sole non-NULL session creation
makes the unsafe state unreachable without adding request-path machinery; HELP/GET/STOP/RESET stay
registered for protocol compatibility.

## The three knobs

These are the only knobs introduced for this work. All are immutable.

| Knob | Levels | Default |
|---|---|---|
| `tomokv-prefetch-io` | `-1`: auto -> 4; `0`: hard off; `1`: legacy handoff; `2`: + consuming cross-client ingress; `3`: + grouped exact reply source; `4`: + validated RAW payload under its existing reply-held reference | `1` |
| `tomokv-prefetch-ex` | `-1`: auto -> 1; `0`: hard off; `1`: metadata/DICT plus FLAT MSET subwaves and the BITCOUNT scan loop; `2`: + ordinary FLAT/MGET and DICT next-op; `3`: + exact-key RAW value data | `-1` |
| `tomokv-reorder` | `-1`: sampled auto; `0`: hard off; `1`: inspect every non-singleton batch with the static GET/BITCOUNT policy | `0` |

The older `tomokv-strict-order` parser is retained and made immutable. Any nonzero value overrides
`tomokv-reorder`; changing it live would mix unstamped and stamped queued fakes. Retaining that
legacy parser is compatibility, not a fourth knob for this work.

## Invariant arguments

### Ownership

- An IO prefetch group touches only the event loop being executed, validates connection/event-loop,
  fd, and `client.tid`, and invokes callbacks as that IO owner.
- Pending lists are mutated only by their IO owner. Cross-thread consumers use client IDs or atomic
  owner-published snapshots, never a foreign list traversal.
- Each producer writes only its own SPSC queue cursors and TLS dirty set. Each worker writes only
  its queue head/retired frontier, scheduler/prefetch counters, and execution state.
- INFO folds immutable atomic snapshots. It does not lock or read live foreign counters.
- Role conversion transfers ownership at explicit adoption/retirement barriers; a listener joins
  the accept group only after worker initialization is proven.

No lock was added to the per-connection request path.

### Ordering

- Scheduling never crosses producer rings or the already-popped prefix.
- Each lane is stable. A deferred equal-key request blocks every later equal-key promotion; hash
  collisions only suppress promotions.
- FLUSH and migration sentinels preserve the entire popped batch verbatim.
- Only a first-in-flight request can enter the early lane. Later requests from that client remain
  deferred, and the existing `cs_barrier`/`flushid` walk emits replies in request order.
- The deferred lane drains before queue retirement or refill, proving the 15-command bound.

The source has multiple IO-producer rings and no default global wall-clock order between them.
This refactor preserves every producer FIFO and introduces no cross-ring movement. Therefore
“arrival order” is defensible at worker admission, not as a timestamp total order across independent
IO event loops. Legacy strict-order supplies a timestamp merge when explicitly configured. If the
product invariant intends literal cross-IO wall-clock order by default, that is a pre-existing
semantic gap and requires a separate global sequencing design; the scheduler neither fixes nor
worsens it.

### Lifetime

- DICT bucket dictionaries persist; the common keyspace constructor rejects free-on-empty in Tomo
  mode.
- A FLAT hint observes table and kvobj shell only inside the worker's QSBR region. It does not retain
  a shell as a lookup result.
- A value-interior address is formed only after an exact-key shell match on the key's owning worker.
  It is immediately used as a prefetch hint; the command performs the authoritative lookup.
- IO reply payload hints follow an existing `bulkStrRef` held by the zero-copy reply; they do not
  create a new pin. That reference remains live until send/teardown. Mutations seeing the shared
  object must copy rather than reallocate that referenced payload in place.
- Callback/wakeup boundaries retain IDs or references, not unprotected raw pointers.

QSBR is not claimed to protect value interiors.

### Two engines

One EX worker per node uses DICT and two or more use FLATSTORE. The DICT FSM, persistent-dict guard,
and next-op bucket lookup are exercised only in the former. The flat home-slot/tag/shell pipeline,
QSBR argument, and grouped MGET path are exercised only in the latter. Expires remains DICT-backed
in both. A null `kvstoreGetDict()` is now an engine selection, not silent prefetch retirement.

## Cost ledger

At the p32 reference rate of 7,943,860 requests/s, one aggregate core-second divided by throughput
is about 125.9 ns/op. Under the brief's accounting convention, one percent is roughly 1.26 ns/op
and the full 3% allowance is roughly 3.78 ns/op. Those are budgets, not measurements or a claim
about individual request latency or service time.

| Mechanism | Source-visible cost |
|---|---|
| Sparse dispatch publication | Ordinary jobs pay one TLS bit OR per successful staged dispatch, then one `ctz` and one release store per distinct worker touched by the producer batch. Cross-shard subrequests publish immediately. Queue-full work occurs only on backpressure. |
| Worker retirement | One relaxed `retired` store per popped batch of 1..16 commands. |
| Exact reply CDB | At most one acquire load per distinct bus represented in the ready client prefix, rather than `num_cdb` loads per client. |
| Embedded pending node | Existing list pointer writes; removes list-node allocate/free. |
| Cross-shard inline argv | One inline-versus-spill decision at group creation/free; no per-operand arena branch. |
| EX prefetch at 0 | One immutable level test per nonempty worker batch. FLAT MSET and BITCOUNT each test the same immutable master before selecting the ordinary/compute-only loop. No prefetch helper, scratch walk, counter update, or hint runs. |
| IO prefetch at 0 | No ingress hook; one null-hook branch per nonempty AE poll and one level test per reply-drain pass. No prefetch walk or counters. |
| Reorder at 0 | One immutable mode guard and the zero-prefix branch per nonempty worker batch, plus one predicted guard only when an IO client's ring transitions empty -> nonempty. No classification, timestamp, dependency table, stats, or early CDB RMW. |
| Reorder at 1 | O(n) opportunity scan and, only for a mixed batch, a second O(n) stable partition for `n <= 16`; 16 pointer slots (128 bytes) of transient stack scratch; owner-local counter increments; up to 15 early parent RMWs in the worst distinct-client batch. |
| Reorder at -1 inactive | One owner-private probe increment per non-singleton enabled batch and an inspection every 64th such batch. |
| Prefetch enabled | Bounded scratch (16 entries for IO and ordinary EX batches, 32 for M-command waves) and owner-local counters; no allocation. On the x86 POPCNT/AVX2 path, BITCOUNT issues one hint per 32-byte scan iteration (64 bytes with AVX-512), targeting 2 KiB ahead; after the loop it adds one invocation counter and one aggregate issued/no-issue counter. The AArch64 NEON loop currently emits no hint and therefore records enabled groups as no-issue. Actual cache/bandwidth cost is intentionally left for measurement. |
| Publication/INFO | EX prefetch copies 26 counters once per 64 popped batches; IO prefetch and scheduler use comparable owner-local cadences and relaxed atomic snapshots. INFO only folds snapshots. Topology/listener/config checks are cold. |

The hard-off arms leave only immutable dispatch guards; they do not run an enabled pipeline that
does nothing. They are not literally compile-time-erased because these are runtime configuration
values. Whether the guards plus the always-on transport ledger fit 3% is not established by a
build and must be measured.

The default is IO level 1, EX auto -> level 1, and reorder off. The metadata/DICT and ordinary
single-key/MGET storage pipeline enters its residency gate and may issue when the shard footprint
exceeds the derived cache threshold. Command-specific FLAT MSET subwaves and BITCOUNT payload scans
obey the master EX level directly rather than that batch-residency gate. Their invocation,
no-issue, and actual-hint counters make that distinction observable.

## 96-core assessment

The tree is bounded and should not index beyond fixed storage at IO 32 + EX 64. That is not the same
as proving it scales:

- every one of 64 workers can still visit 32 producer-ring headers per logical pass: 2,048 ring
  header visits across the pool even when empty;
- static `jobs[2048]` storage is about 33.4 MiB at 64 workers x 33 compiled producer slots;
- the corresponding freeback rings are about 16.8 MiB; and
- on a multi-L3 machine, 64 cache-line-isolated CDB masks consume 4 KiB per real client.

Producer publication is now sparse, but worker polling is still O(EX x IO). At full width the flip
controller has no actuator headroom and is disabled. The branch is therefore capacity-safe, not
96-core performance-proven.

## Evidence adopted, rejected, and corrected

| Input | Decision |
|---|---|
| `ARCH_BRIEF.md` | Treated as premise: owner publication, DICT/FLAT split, real-lookup authority, QSBR boundary, reply ordering, and AMAC rejection. |
| Shinjuku source and `SCHED_DESIGN.md` | Kept bounded cost classes and fairness concepts. Rejected global any-worker queues, floating-age scans, enqueue-drop behavior, IPI/ucontext preemption, and lack of key dependencies. |
| `MQ_DESIGN.md` | Kept stable lanes and closed no-refill reasoning. Rejected persistent per-worker multi-queues, timestamps, and dependency-table machinery as unproven against the 3% budget. |
| `HEAT_SCHED.md` | Kept the advice to schedule before prefetch. Rejected heat-driven promotion until shadow data shows conditional service time predicts benefit. |
| `COMM_AUDIT.md` | Adopted sparse producer publication, publish-before-full-retry, exact CDB capture, bounded batches, and owner snapshots. Corrected its possible dropped-push concern: all live callers retry. |
| `KNOB_SURFACE.md` | Adopted exactly three masters and level semantics. Rejected its `16/num_cdb` reply width because exact captured-bus probing makes occupancy-capped 16 source-correct. Rejected its persistent timestamp merge for the default scheduler. |
| Prefetch reviews | Adopted flat storage staging, DICT KVOBJ/VALDATA separation, live DICT next-op, grouped MGET/MSET, sequential BITCOUNT staging, authoritative relookup, and stage/noissue counters. Rejected the alleged cached-dict UAF: source deliberately omits free-on-empty; the new constructor guard preserves that premise. |
| Allocation reviews | Adopted the embedded list node and group-owned argv storage. Rejected the arena and unmeasured default-on MSET ownership move. |
| Dead-code review and safety audits | Applied sampler/eviction, corrected module, unused-field, uncalled-helper, dominated-cluster, and narrow IO-role-guard deletions. Rejected the claimed duplicate bucket hashing: source showed the full routing hash was useful and is now carried to prefetch. Rejected original broad module/docs deletions that removed observables. |
| Individual correctness diffs | Existing mailbox CAS, packed request, error-stat sharding, IO utilization, active expiry, and runtime REPLICAOF gates were retained; role/listener/transport gaps were re-derived where their patches were stale. The partial HOTKEYS patch was replaced by safe admission refusal. |
| Scheduler implementation and harness | Re-derived the classifier and moved scheduling before prefetch. The supplied long-MGET/SCAN harness does not activate this implementation because both shapes fence; it cannot validate scheduler efficacy unchanged. |
| `SCALE_AUDIT.md` | Missing from the supplied files. No conclusion is attributed to it. |

### Complete supplied-input disposition

This ledger accounts for all 100 supplied files: 6 design artifacts, 59 patch/result artifacts,
and 35 review/audit artifacts. `x.{patch,RESULT.md}` below denotes both named files.

#### Designs and standing reviews

| Input | Disposition |
|---|---|
| `designs/knob-consolidate_KNOB_SURFACE.md` | Adopted with corrections. Kept the three immutable master knobs and level model. Corrected reply width because exact captured-CDB probing removes the stated `16/num_cdb` constraint; retained compatibility parsers where removal would change boot behavior. |
| `designs/sched-comm_COMM_AUDIT.md` | Adopted/re-derived. Used sparse producer publication, publish-before-retry, exact CDB capture, bounded batches, retirement frontiers, and owner snapshots. Its possible ignored-full-return concern was stale: all live callers retry. |
| `designs/sched-harness_RESULT.md` | Evidence only. Not installed or run. Its long MGET/SCAN cells fence in the implemented first-version scheduler, so it cannot establish scheduler engagement unchanged. |
| `designs/sched-heat_HEAT_SCHED.md` | Partially adopted. Scheduling-before-prefetch and flat slot/shell staging were used. Heat promotion was rejected until shadow data proves popularity predicts service cost; broad value-interior rejection was replaced by exact-key qualification plus the source lifetime protocol. |
| `designs/sched-mq_MQ_DESIGN.md` | Partially adopted. Kept stable lanes, no-refill epochs, conservative dependencies, and the cross-producer-linearization warning. Rejected persistent 64-command queues, timestamps, dependency tables, and its extra knob. |
| `designs/sched-study_SCHED_DESIGN.md` | Re-derived. Kept non-preemptive closed-batch conflict-aware scheduling and early completion publication. Rejected Shinjuku preemption/global dispatch and changed the long class and ordering relative to the supplied sketch. |
| `reviews/rev-prefetch_PREFETCH_REVIEW.md` | Adopted as the primary prefetch inventory. Its FLAT gap, DICT KVOBJ/VALDATA split, IO grouping, next-op, MGET, and counter findings shaped the implementation. |
| `reviews/prefetch-review2_PREFETCH_REVIEW2.md` | Used selectively. Its storage-path audit was useful. Its cached-dict UAF conclusion is explicitly refuted by the premise and source; the constructor now enforces persistent Tomo keyspace dictionaries. Its blanket next-op, value, and IO rejections were not followed. |
| `reviews/rev-alloc_ALLOC_REVIEW.md` | Adopted selectively. Implemented the embedded pending node and group-owned sub-argv storage. Deferred MGET result descriptors and rejected the arena/default-on MSET proposals. |
| `reviews/alloc-review2_ALLOC_REVIEW2.md` | Adopted as allocation-count evidence. Used its pool/lifetime accounting to prioritize the same two safe reductions; did not treat speculative proposals as established wins. |
| `reviews/rev-dead_DEAD_CODE_REVIEW.md` | Used only through safety audits and live-source checks. Several findings were right; the “duplicated bucket hashing” finding was false because the full routing hash remains useful. |
| `reviews/stability-register_FAILURE_MODES.md` | Checklist/partial adoption. Drove startup, listener, role rollback, queue publication, FLUSH, notifier, and count fixes. It was not a patch; unresolved liveness/capacity modes remain in `RISK.md`. |

#### Allocation, correctness, prefetch, and scheduling artifacts

| Input(s) | Disposition |
|---|---|
| `diffs/alloc.{patch,RESULT.md}` + `reviews/rv-alloc_REVIEW.md` | Adopted. Embedded `clients_pending_ex_node` and group-owned inline/spill sub-argv vectors were re-based into `dd0eef77a`; the SOUND review's ownership argument remains applicable. |
| `diffs/alloc-arena.{patch,RESULT.md}` | Rejected. It adds a fourth knob and materially expands parser, rewrite, storage, propagation, blocking, and module lifetime contracts. The escape audit is substantial but not enough to make every future/out-of-tree retention route closed. |
| `diffs/alloc-mset.{patch,RESULT.md}` + `reviews/rv-alloc-mset_REVIEW.md` | Rejected for this pass. The review found missing ownership tests and a release gate for the newly default-on per-value atomic RMW. The existing explicit move arm remains available; its default was not changed. |
| `diffs/errstat.patch` | Retained upstream. Present as `ac55943e4`; per-IO error-stat sharding was not lost. |
| `diffs/flipctx.patch` | Retained and extended. The CAS flip claim is upstream as `7b7a85855`; later role/cancellation work preserves and builds on it. |
| `diffs/mbox.patch` | Retained and extended. Packed mailbox publication is upstream as `fe9e6d864`; later generation/acknowledgement handling closes additional cancellation races. |
| `diffs/iosat.patch` | Retained upstream. Real IO-thread utilization is present as `7880fd0eb`. |
| `diffs/iosat-cheap.{patch,RESULT.md}` + `reviews/rv-iosat-cheap_REVIEW.md` | Rejected. The DEFECTIVE review showed pass-count sampling fabricated zero/lumpy utilization, left the controller live at “off,” and misstated the cost bound. |
| `diffs/task-expiry.{patch,RESULT.md}` | Re-derived. Existing owner-worker whole-key and hash-field active-expiry fixes were retained; runtime `REPLICAOF host port` is now rejected in sharded mode. |
| `diffs/task-observability.{patch,RESULT.md}` | Partially re-derived. Added owner-published client/count state and precise scheduler/prefetch/no-issue/backpressure counters where required. The broad always-on INFO expansion was not merged wholesale. |
| `diffs/task-parked.{patch,RESULT.md}` | Superseded by broader role work. Its stale PARKED premise was accepted as stale; the real activation, retirement, cancellation, listener, count, FLAT-orphan, and rollback gaps were fixed across `b3316cb20` through `1f58186a8`. |
| `diffs/hotkeys.patch` + `diffs/fix-hotkeys.{patch,RESULT.md}` + `reviews/rv-hotkeys_REVIEW.md` | Rejected and replaced with admission refusal. The original was non-applicable/DEFECTIVE; the follow-up still left shared heaps, counters, session lifetime, and worker-bypass coverage unresolved. `HOTKEYS START` now refuses creation of unsafe shared state. |
| `diffs/prefetch.{patch,RESULT.md}` + `reviews/rv-prefetch_REVIEW.md` | Re-derived. Kept the full hash, FLAT stages, DICT split, live DICT next-op, and counters. Rejected the review's cached-dict UAF claim per the settled premise; fixed its valid dormant/default/hard-off objections through the master knob and source guard. |
| `diffs/prefetch2.{patch,RESULT.md}` | Re-derived under the consolidated knob. Kept stage arithmetic, exact-key qualification, live DICT next-op, and no-issue observability; discarded its independent controls and divergent intermediate structure. |
| `diffs/guard-prefetch-invariant.{patch,RESULT.md}` | Adopted. The common Tomo keyspace constructor rejects `KVSTORE_FREE_EMPTY_DICTS`, making the persistent-dictionary lifetime premise executable. |
| `diffs/prefetch-mget.{patch,RESULT.md}` + `reviews/rv-prefetch-mget_REVIEW.md` | Re-derived. The review correctly rejected a second divergent flat helper and modifiable cross-thread gate. MGET now shares the common FLAT grouped probe under `tomokv-prefetch-ex`. |
| `diffs/prefetch-io.{patch,RESULT.md}` | Re-derived. Replaced its two knobs with `tomokv-prefetch-io`; ingress is the fired-event consumer and replies are grouped across clients with owner-local boundaries and stable-ID wakeups. |
| `diffs/sched-impl.{patch,RESULT.md}` | Heavily re-derived. Kept the narrow GET/BITCOUNT, dependency-mask, closed-batch, early-publication concept. Scheduling now precedes prefetch, uses transient lanes, fences control work, proves a 15-request bound, and includes adversarial fired-event fixes. |
| `diffs/task-preflight.patch` | Skipped. It changes only validation harnesses, was stale relative to the final knob/scheduler shapes, and no tests or servers were permitted. |

#### Dead-path artifacts and their reviews

| Input(s) | Disposition |
|---|---|
| `diffs/dead01-sampler.{patch,RESULT.md}` + `reviews/rv-dead01-sampler_REVIEW.md` + `reviews/sa-dead01-sampler_SAFETY.md` | Adopted. Removed the write-only dispatch-to-retirement sampler; no config or INFO observable was removed. |
| `diffs/dead02-polythreads.{patch,RESULT.md}` + `reviews/rv-dead02-polythreads_REVIEW.md` + `reviews/sa-dead02-polythreads_SAFETY.md` | Partially adapted. Removed only source-current constant `poly_threads == 1` IO-poll guards. Retained legacy thread-main fallbacks because the reviewed broad patch predates newer activation/rollback code. |
| `diffs/dead03-modules.{patch,RESULT.md}` + `reviews/rv-dead03-modules_REVIEW.md` + `reviews/sa-dead03-modules_SAFETY.md` | Rejected as submitted. The review found observable command-schema and boot-diagnostic regressions; the safety audit was PARTIALLY-UNSAFE. |
| `diffs/fix-dead03.{patch,RESULT.md}` + `reviews/sa-fix-dead03_SAFETY.md` | Adopted with live-source adaptation. Removed unreachable dynamic loading internals while retaining `loadmodule` parsing/fatal policy, MODULE command metadata/reply schemas, bundled Vector Sets, and unresolved-config behavior. |
| `diffs/dead04-copyengine.{patch,RESULT.md}` + `reviews/rv-dead04-copyengine_REVIEW.md` + `reviews/sa-dead04-copyengine_SAFETY.md` | Skipped after rebase audit. It was safe on its reviewed base, but the stale patch would now remove newer `tm_mig_flip_action` abort rollback. Safety does not transfer across that semantic change. |
| `diffs/dead05-nextop.{patch,RESULT.md}` + `reviews/rv-dead05-nextop_REVIEW.md` + `reviews/sa-dead05-nextop_SAFETY.md` | Superseded. Accepted the constant-predicate proof, but the EX FSM was replaced wholesale; the old aliases/predicates and inaccurate comments no longer survive. |
| `diffs/dead06-retiredknobs.{patch,RESULT.md}` + `reviews/rv-dead06-retiredknobs_REVIEW.md` + `reviews/sa-dead06-retiredknobs_SAFETY.md` | Skipped. Safe but startup-only/no-op with no runtime or allocation value; retained to avoid spending rebase risk on a placeholder-only cleanup. |
| `diffs/dead07-fields.{patch,RESULT.md}` + `reviews/rv-dead07-fields_REVIEW.md` + `reviews/sa-dead07-fields_SAFETY.md` | Adopted. Removed the six write-only fields, orphan allocations, and assignments; updated source-current commentary rather than preserving the review's noted stale replacement text. |
| `diffs/dead08-nocaller.{patch,RESULT.md}` + `reviews/rv-dead08-nocaller_REVIEW.md` + `reviews/sa-dead08-nocaller_SAFETY.md` | Adopted and completed. Removed the 14 production helpers and followed the review's closure through readless connection/RIO callback residue; retained the two documented debugger helpers. |
| `diffs/dead09-evictbuckets.{patch,RESULT.md}` + `reviews/rv-dead09-evictbuckets_REVIEW.md` + `reviews/sa-dead09-evictbuckets_SAFETY.md` | Adopted with observables preserved. Removed unreachable bucket machinery while retaining `maxmemory-clients`, `evicted_clients`, `CLIENT NO-EVICT`, and disabled-feature diagnostics/help. |
| `diffs/dead10-cluster.{patch,RESULT.md}` + `reviews/rv-dead10-cluster_REVIEW.md` + `reviews/sa-dead10-cluster_SAFETY.md` | Adopted. Removed only cluster-positive arms dominated by the retained boot-fatal check; cluster config/parser/source linkage remains. |
| `diffs/dead12-staledocs.{patch,RESULT.md}` + `diffs/fix-dead12.patch` + `reviews/rv-dead12-staledocs_REVIEW.md` + `reviews/sa-dead12-staledocs_SAFETY.md` | Rejected. `fix-dead12.patch` is byte-identical to the defective original. Reviews found false-success validators, lost live coverage, and stale ownership prose still present; no safe corrected artifact was supplied. |

The remaining uncertainty in these dispositions is explicit: the scheduler proof assumes worker
admission is the cross-IO-producer linearization point; the 3% budget is unmeasured; deletion
reachability proofs are in-tree; and 32 IO + 64 EX is bounds-safe but not performance-proven.

## Deliberately not done

- No AMAC flat probe, preemption, IPI, ucontext, persistent multi-queue, global timestamp queue, or
  heat promotion.
- No same-client IO prefix walk; it duplicates the eventual consumer traversal and was a measured
  negative.
- No per-command arena and no default-on MSET value move.
- No partial HOTKEYS concurrency patch; START is refused instead.
- No attempt to make worker polling sparse on the consumer side or shrink the compiled queue/freeback
  matrices. That is the remaining 96-core transport project.
- No wholesale dead-code application. Several otherwise audited patches predate the role,
  prefetch, and configuration rewrites and no longer apply cleanly; an audit proves its reviewed
  diff, not an improvised rebase. Only the current-source-safe IO-role subset was adapted. The stale
  copy-engine deletion would remove newer abort rollback, and the no-op retired-knob cleanup has no
  runtime value, so both remain outside this boundary.
- No dynamic-module, replication, AOF, eviction, or transaction support was invented for the
  sharded keyspace. Existing unsupported paths still fail loudly.
- No supplied preflight/harness patch was run or used as runtime evidence; tests and servers were
  explicitly prohibited.

## Least confidence and decisive measurements

The least certain result is scheduler efficacy, not its closed-batch ordering proof. HEAD eligibility
may be rare at pipeline depth 32, and an early completion replaces suffix coalescing with up to one
release RMW per distinct selected parent. The decisive workload is distinct clients producing
`[large BITCOUNT(A), HEAD GET(B)]`, plus a same-key negative control. Measure throughput, p99/p99.9,
opportunities, promotions, early completions/RMWs, dependency refusals, maximum bypass, and bound
violations. Violations must be zero. The supplied MGET/SCAN harness is not this test.

Second is prefetch value. Compare IO levels 0..4 and EX levels 0..3 in both DICT (one worker/node)
and FLATSTORE (two or more), with seeded data larger than the effective L3. Require the stage
counters, including BITCOUNT invocation/no-issue, to prove the intended arm issued. Record
throughput/latency, LLC misses, stalled cycles, memory bandwidth, and freeback/refcount pressure.
Delete/rehash/flat-resize and write-before-read loads are the lifetime stress cases.

Third is full-width transport. On the target 32/64 topology, measure empty-pass cycles, ring-header
LLC and remote-NUMA traffic, per-client CDB memory, and throughput while increasing IO and EX
independently. This settles whether O(EX x IO) polling and the ~50 MiB compiled ring matrices are
acceptable or require an active-producer bitmap on the consumer side.

Finally, exercise listener/TLS/address shapes and repeated flip grow-front/grow-back cancellation,
FLUSH, notifier failure, and FLAT resize/reclaim windows. Those are cold paths where a successful
build provides the least evidence.

## Verification

After `8782313a4`, `pgrep -x memtier_benchma` returned no load-generator process and `make -j4`
completed with exit status 0. No new warning was emitted by the rebuilt source. `git diff --check`
also passed before each source commit. Per instruction, no server, benchmark, or test was started.
