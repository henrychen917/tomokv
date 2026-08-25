# Opt-in epoch-MVCC atomics

`--atomic 1` makes `MSET`, `MSETNX`, multi-key `DEL`, and `UNLINK` atomic across shards. `MGET`,
`EXISTS`, `TOUCH`, `KEYS`, and exact `DBSIZE` resolve one committed cut while tracking is active.
The default is `--atomic 0`; a shard with no pending group entry follows the original store path,
allocates nothing, and pays one predicted branch. `--atomic-window` defaults to 256 admitted atomic
write groups (zero is unlimited). Both knobs are numeric and live through `CONFIG SET/GET`.

## ATOMICS V3: group-scoped pending entries

V3 deletes the V2 per-key record table and candidate-node chains. One atomic owner task now creates
one pooled `AtomicEntry` for its shard span in `ScatterState::key_order`. The entry retains the group
decision pointers, the span coordinates, one 64-bit hash-membership mask, and a trailing parallel
array of displaced `KvObj*` predecessors. Key bytes are not copied: installed values supply stable
keys, while DEL/UNLINK use arena-owned empty-string key anchors because their physical install is a
tombstone. The steady write loop is therefore one physical replacement/erase and one parked-pointer
store per key; group linking, decision references, and allocation are paid once per shard task.

Each shard has a normally empty intrusive pending-entry list and a 64-bucket intrusive connection
index used only for exact same-connection undecided hazards. With an empty list, point lookup and the
ordinary write handlers are unchanged. With entries present, the resolver rejects most entries by
the membership bit, checks the referenced span for exact key equality, and chooses the largest
committed epoch not newer than the read cut. The oldest matching parked pointer is the base; each
later parked pointer is the candidate immediately before that install, and the physical object is
the newest candidate. Epoch-zero, abandoned, and too-new installs are skipped. This computation is
order-independent for overlapping groups. Expired parked predecessors resolve absent.

An ordinary write touching no pending entry stays on its original path. One that does touch an entry
deep-clones the resolved value and installs a pooled one-key plain pseudo-entry with its own ticket,
so existing in-place collection handlers cannot mutate a protected predecessor. Same-owner
multi-key commands retain localfast and prepare every touched pseudo-entry before drawing tickets.

Cleanup removes the contiguous decided prefix strictly below the global read floor and no newer
than its pre-floor commit cutoff. Monotonic install/ticket order is proved in one linear pass and
then cleanup only frees parked predecessors and unlinks entries. If tickets invert, membership and
exact-key checks decide whether the same direct collapse is safe; an actual overlap uses a reusable
transient argmax table. An abandoned prefix reinstalls its predecessor, or splices it into the first
surviving occurrence of that key. This is the rollback-free abort. Output-materialized reads release
their epoch floor before ordered socket retirement; zero-copy string results retain their existing
store borrow instead. While atomic work is live, each IO admits at most eight unresolved snapshot
groups so a deep MGET pipeline cannot pin thousands of entries and turn list resolution quadratic.

No command path retains the V2 side map. The per-shard value and entry freelists remain because they
remove steady-state allocator traffic. `atomic_records_freed` is kept as a compatibility counter but
now counts retired group/plain entries; `atomic_entries` is the explicit cumulative entry gauge and
`atomic_pending_entries` is the current live gauge. `atomic_cleanup_fast/slow` expose the monotonic
and inversion/abort cleanup work.

### V3 instruction and throughput audit

The owner reference that motivated this lane was 504 cycles, 607 instructions, IPC 1.20, and 7.0
cache misses per written key at 1.64M commands/s OFF, versus V2's 920 cycles, 1,979 instructions,
IPC 2.15, and 15.8 misses at 859k commands/s ON. Thus V2 added 1,372 instructions/key, while the
10% goal allowed about 60.

The final V3 checkout was measured on 2026-08-25 with the same 8-core 6:2 placement: server CPUs
`240-243,248-251`, executor counters on `243,251`, and memtier on `244-247,252-255`. Every cell used
8 threads, 8 clients/thread, pipeline 32, 32-byte data, random command keys, and 30 seconds.

| Pure `MSET-8`, 100k keys | Commands/s | cycles/key | instr/key | IPC | misses/key |
| --- | ---: | ---: | ---: | ---: | ---: |
| V3 checkout, atomic OFF | 889,479 | 871 | 608 | 0.70 | 7.66 |
| V3 checkout, atomic ON | 431,588 | 1,798 | 1,594 | 0.89 | 14.27 |

V3 removes 385 instructions/key (19.5%) from the supplied V2 ON count, but the local ON tax is still
986 instructions/key and throughput is 48.5% of OFF (`-51.5%`). Therefore the requested 10-15%
pure-write target is **not met**. Sampling attributes the remaining executor instruction volume
primarily to physical exchange, entry-prefix collapse, owner-task execution/completion, and
same-connection hazard checks. Group scoping alone did not make cleanup and publication amortization
cheap enough for the roughly 60-instruction allowance.

| Final 30-second cell, 100k keys | OFF commands/s | ON commands/s | ON/OFF |
| --- | ---: | ---: | ---: |
| 1:1 `MSET-8:MGET-8` | 943,770 | 461,369 | 48.9% |
| populated pure `MGET-8` | 1,586,424 | 1,393,772 | 87.9% |
| single-key 1:1 `SET:GET` | 7,265,204 | 7,653,455 | 105.3% |
| populated `MSETNX-8` | - | 580,888 | - |

The mixed 20% target is also not met. Point reads and single-key writes do not create pending
entries; single-key parity holds, while the cross-shard pure-read snapshot plumbing costs 12.1% in
this run. A separate ON `MSET-8` 30-second sustained run with key maximum 100M completed at 418,484
commands/s and drained to `atomic_pending_entries=0` (observed `DBSIZE=2,933,667` under memtier's
shared random streams). The 100k final ON run likewise drained to zero and fired
`atomic_entries=83,545,907`, `atomic_promotions=103,593,240`, and `atomic_chain_max=359`; predecessor
reads are correctly zero in blind pure-write traffic.

### V3 validation record

The final quick gate reports `15 ok, 0 FAIL`; the release and ASAN builds enforce
`sizeof(Op)==336` and `sizeof(Client)==1984`. The atomic batteries also pass under ASAN with no
sanitizer report. Their non-vacuous observations include an OFF torn control, zero ON tears,
overlapping writers with an exact final group, DEL-vs-MSET all-or-nothing, abandoned MSETNX
invisibility, pipelined atomic/plain RYOW, 63 admission-window stalls, and connection churn ending at
`inflight=0,pending=0`. One ASAN run moved predecessor reads by 5,456, promotions by 173,456, and
retired 5,784 churn entries. Redis 8.9 differential runs for `string` (4,033 ops), `xshard` (4,276),
and `cgaps` (3,310) each produced zero diffs at both `--atomic 0` and `--atomic 1`.

The command templates remain `MSET __key__:0 __data__ ... __key__:7 __data__` and
`MGET __key__:0 ... __key__:7`, passed via `--command-key-pattern=R`. The sustained arms use
`--test-time 30 --key-minimum 1` with `--key-maximum 100000` and `100000000`, respectively.

## ATOMICS V2 performance rework (historical)

The measured 8-core loopback decomposition that motivated V2 was:

| Cell (8 keys, t8/c8, pipeline 32, 100k keyspace) | Commands/s | Cost exposed |
| --- | ---: | --- |
| atomic OFF `MSET-8` | 1.67M | single-hop scatter ceiling |
| atomic OFF `MSETNX-8` | 637k | two hops plus connection parse barrier, no MVCC |
| atomic ON V1 `MSET-8` | 198k | two hops, barrier, and V1 MVCC allocation/install |

V2 changes the write path in four related places:

1. **Single-hop abandon-as-invisibility.** Each touched owner performs capacity/admission, record
   and value preparation, and the invisible version install in one task. A refusal release-marks the
   group abandoned. The last completer replies with the selected error and publishes nothing, or
   draws `T = ++commit_seq` and release-publishes the group epoch. `MSETNX` aggregates existence and
   replies 0 without publishing; `DEL`/`UNLINK` install tombstones and aggregate existed counts.
   This removes the second task round and the inter-hop barrier; rollback is unnecessary because an
   epoch-zero candidate is unreachable to every resolver and is reclaimed by owner cleanup.
2. **No atomic connection parse barrier.** Atomic writes pipeline freely. The owner parks only a
   task that touches the same connection's own undecided group node on the same key. Foreign nodes
   are skipped, cross-key operations proceed, and a separate resource-backpressure bit leaves an
   unconsumed frame parked only while the admission window is full. Whole-shard readers treat every
   own undecided node on that shard as a touched-key hazard. This recovers the concurrency hidden by
   the 1.67M-to-637k structural drop without importing an arrival-order frontier.
3. **MVCC allocation diet.** The side map is an owner-only open-address table keyed by hash with
   exact pooled-key comparison. Records have a 24-byte inline key, pooled long-key tails, an embedded
   first candidate, and a compact base predecessor. Additional nodes, records, and raw/int string
   values use per-shard intrusive freelists with arithmetic `good_size` classes. After warmup the
   common atomic string-write path performs no heap allocation. Group lifetime references are
   aggregated once per owner rather than contending once per key, and owner sweeps are batched on
   normal execution passes plus a low-frequency idle sweep instead of posting a cleanup task per
   group.
4. **Localfast under tracking.** Same-owner multi-key commands retain their original handler when
   touched keys have no records (one owner-only side-map probe per key). Reads with records resolve
   inline. Writes with records clone only those recorded keys into direct plain versions and then
   run the original handler against the clones; they never wait for an unrelated global read floor.

The structural wins are intentionally separable: point 1 removes an owner round, point 2 removes
connection-wide serialization, point 3 removes steady-state allocator/hash/reference traffic, and
point 4 restores the original same-owner fast path. The final combined result on the same 8-core
loopback shape was:

| Final V2 cell (30 seconds) | Commands/s | Result |
| --- | ---: | --- |
| atomic OFF `MSET-8` | 1.342M | local same-run ceiling |
| atomic ON `MSET-8` | 827k | 61.6% of local OFF; 4.18x the 198k V1 cell |
| atomic ON populated `MSETNX-8` | 1.218M | exceeds the 500k target |
| atomic ON 1:1 `MSET-8:MGET-8` | 907k combined | exceeds the 500k mixed target |
| atomic ON single-key 1:1 `SET:GET` | 6.534M combined | parity with OFF 6.477M (+0.9%) |

This host's final OFF cell was 19.6% below the 1.67M decomposition reference; the ON/OFF ratio is
above the 60% target and normalizes to 1.029M at that reference ceiling, although the locally
observed absolute ON cell was 827k. The individual point gains were not claimed from synthetic
ablations: points 1 and 2 remove the task round and parse barrier by construction (the overlap arm
measured a 2.18x pipelined/serial ratio), point 3 is what makes the resulting steady-state path
pool-only, and point 4 is directly evidenced by the single-key ON/OFF parity cell.

All cells used `memtier_benchmark -s 127.0.0.1 -p 7899 -t 8 -c 8 --pipeline 32
--test-time 30 --key-minimum 1 --key-maximum 100000` with default 32-byte data. The eight-key
templates were `MSET[ NX] __key__:0 __data__ ... __key__:7 __data__` and
`MGET __key__:0 ... __key__:7`, each with random command keys; the mixed cell assigned ratio 1 to
each template. The populated `MSETNX` cell followed an `MSET` population pass over the same range.
The single-key cells used the built-in `--ratio 1:1 --key-pattern=R:R` shape.

## V2 representation and publication (superseded)

`KvObj` and the command/connection ABI sizes remain unchanged. A shard lazily creates its MVCC map
on first tracked install. Each record owns a stable pooled key, a compact base value, and an
unsorted candidate chain. A candidate contains a `KvObj*` (null is a tombstone), its origin
connection ID, and either a group epoch/abandon pointer or a direct plain-write epoch.

Owners may install different groups in different physical orders. A present-to-present atomic
replacement may occupy the existing table slot while still invisible because all point reads
resolve through the record and cardinality is unchanged. Inserts and tombstones remain side-only
until promotion. Publication alone changes visibility; there is no publish frontier, group lock,
cross-client ordering wait, rollback, or physical-simultaneity requirement.

## V2 visibility and same-connection order (superseded)

A tracked read selects the candidate with the largest nonzero committed epoch at or below its cut;
the base predecessor is eligible at epoch zero. Foreign undecided candidates are ignored. A
same-connection candidate that commits after a pipelined reader captured its cut is overlaid by
origin ID after the owner hazard has waited for the decision, providing RYOW without moving the
registered cut. Resolution and promotion always compute an epoch argmax and never infer order from
chain or physical-link order.

The deferred queue is owner-local and separate from normal work. When an op finds its own undecided
node on a touched key it is requeued; the owner continues normal inbox work. Later same-connection
tasks sharing that key inherit the earlier deferred dependency. Cross-key work on the same
connection and all foreign-connection work continue immediately.

Ordinary writes that encounter records create direct committed versions before invoking their
existing handlers. This preserves old snapshots while retaining in-place collection mutation.
Same-owner multi-key handlers reserve all required direct-version context before drawing tickets,
so activation cannot fail halfway through publication.

## V2 lifetime and promotion (superseded)

Each IO thread publishes the minimum **exclusive** read floor of its active scatter groups: for an
inclusive cut `S`, it publishes `S + 1` (or `UINT64_MAX` when inactive). The server floor is the
minimum publication. The freeing invariant is:

> A version is freed only after every version in its key record is decided and has an epoch
> strictly below the global floor. Consequently the promoted argmax is valid for every active and
> future reader, and no active reader can dereference a retired predecessor.

Publishing the successor lets the winner at the oldest inclusive cut become the sole physical
representation while preserving the strict inequality. Snapshot registration publishes its first
cut and then confirms `commit_seq`. Cleanup loads a commit cutoff before the floor and refuses to
promote anything newer than the cutoff. Those operations are sequentially consistent, closing the
publication/reclamation race without making resolution wait.

Promotion is owner-only and bounded. The next owner touch may promote its key; every fourth normal
owner batch runs a larger sweep and idle owners run a small low-frequency sweep. A bounded table
walker suppresses promotion only while its cursor is active, preventing a side-only insert from
moving into an already-scanned physical slot. Losers use the existing borrow retirement rules.
`ScatterState` arenas named by remaining nodes stay in their IO pool's deferred list until their
per-owner references reach zero.

Turning atomic mode off affects only newly admitted commands. In-flight groups decide, readers keep
consulting surviving maps, and the last record promotion drops the shard's tracking reference.

## V2 admission, diagnostics, and validation (superseded)

Admission reserves one memory-window slot before allocating the scatter arena. At the cap, prepare
returns backpressure without consuming the RESP frame; other clients and owners continue. Group
retirement releases the slot. The ticket is drawn only at successful publication, so the window is
a resource bound, never an ordering device.

`INFO STATS` exposes `atomic_groups`, `atomic_inflight`, `atomic_predecessor_reads`,
`atomic_chain_max`, `atomic_promotions`, `atomic_window_stalls`, and `atomic_records_freed`.
`tests/atomic_torn.py` requires predecessor reads and promotions to move. `tests/atomic_ryow.py`
covers pipelined atomic-write/read RYOW, atomic-then-plain same-key order, abandoned `MSETNX`
invisibility to own and foreign readers, and measured same-connection cross-key overlap.

Movers and store-producing commands remain outside the cross-shard atomic command set: `RENAME`,
`RENAMENX`, `COPY`, `SMOVE`, `LMOVE`, `RPOPLPUSH`, `SINTERSTORE`, `SUNIONSTORE`, `SDIFFSTORE`,
`BITOP`, `PFMERGE`, `LMPOP`, `ZMPOP`, `ZRANGESTORE`, and `SORT STORE`. They resolve recorded inputs
and stamp writes to recorded destinations but retain their prior command-level semantics. FLUSH
installs an owner-local ticketed tombstone cut before clearing plain slots. `SCAN`, random-key,
expiry, and eviction retain their existing non-snapshot command semantics while respecting record
ownership and predecessor lifetime.
