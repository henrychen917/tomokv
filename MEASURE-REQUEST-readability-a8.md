## readability-a8

Branch `cx-readability-a8`, base `7595a6705`. Frozen comparison binary:
`/home/user/Projects/bins/readability-pre-5c363128/tomokv` (release `5c36312818`).
No push, benchmark, full iteration, gate row, or expected-count change is requested.

### Documentation and local names

The owned files describe owner access, foreign capture, release/acquire publication,
QSBR retirement, borrowed wire storage, snapshot back-pressure and MVCC ownership.
Historical measurements/decisions are archived in
[the decision log](docs/decisions/readability-a8.md); no new throughput claim is made.
The overview no longer claims all KvObj bytes are immutable or that FlatStore contains
no atomics. Layout comments describe the actual asserted ranges and alignment limits.

Counts from the lexical audit: **94 rewritten comment groups**, **28 added or expanded
contracts**, **11 phase landmarks**, **5 file headers**, **7 renamed local bindings**.
A comment group is the non-tool comments at a single preprocessing-token boundary;
rewrites include expanded contracts at existing boundaries. Two old snapshot phase
comments above functions are not counted as new internal landmarks. The 28-contract
inventory below includes 9/9 functions over 50 token-bearing code lines and all reviewed
types with non-obvious ownership; the existing ReadLocalPrefetchCapture contract is retained.

| Function | Old local | New local | Bindings |
|---|---|---|---:|
| `snapshot_progress_record` | `n` | `emitted_bytes` | 2 |
| `snapshot_progress_record_read_local` | `n` | `emitted_bytes` | 2 |
| `random_live` | `paused`, `choose` | `expiry_paused`, `consider_key` | 2 |
| `ExpireIndex::random_hash` | `t` | `table_index` | 1 |

No externally visible name, member, type, macro, namespace, string literal or tool marker
is renamed. [Scoped rename inventory](docs/readability-a8/renames.json).

### Contract claim evidence

Caller discovery searched the whole worktree's C++ headers, sources and includes, including
R7 bodies and fixtures, before assigning roles. The report's owner contracts are caller
preconditions, not a claim that FlatStore dynamically checks the executing thread.
Live CONFIG status is taken from `src/cmd/t_server.cc:446` (`read-local` immutable), not
config.h. Arming, sink transfer and shutdown are separate lifecycle operations.

| Contract | Claims and code evidence |
|---|---|
| `StoreSizeState` | Allocation/destruction and relaxed monitoring publication; cursor stays owner-local. `src/store/flatstore.h:70`, `src/cmd/storesize.cc:109`, `src/cmd/storesize.cc:70`, `src/cmd/storesize.cc:129` |
| `ExpireIndex` | Owns hash/state buffers; serialized access, bounded normal migration plus drain backstop; false on insertion allocation failure. `src/store/flatstore.h:121`, `src/store/flatstore.h:150`, `src/store/flatstore.h:335`, `src/cmd/storesize.cc:56` |
| `ReadLocalStoreState` | Owns extended allocation and resize record; borrows sink; owner counters versus atomic probe/filter access. `src/store/flatstore.h:532`, `src/store/flatstore_atomic.inc:1127`, `src/store/flatstore_atomic.inc:1190`, `src/store/foreign_read_safety.h:22` |
| `FlatStore` | Owner command/maintenance access; replay and post-join teardown; object/version/borrow/QSBR lifetime, failed admission. `src/store/flatstore.h:564`, `src/core/ex_execute.inc:46`, `src/main.cc:429`, `src/persist/aof.cc:3756`, `src/store/flatstore.h:1789`, `src/core/read_local.h:320` |
| `ReadLocalProbe` | Non-owning result, capture lifetime and validation state. `src/store/flatstore.h:591`, `src/store/flatstore.h:910`, `src/core/ex_loop.h:1158` |
| `ReadLocalTable` | Borrowed allocation, acquire-loaded fields and validation before indexing. `src/store/flatstore.h:611`, `src/store/flatstore.h:2907`, `src/store/flatstore.h:2909` |
| `ReadLocalTopology` | Pair of borrowed views filled/validated together. `src/store/flatstore.h:617`, `src/store/flatstore.h:2907` |
| `ReadLocalTableGuard` | Move transfers closing duty; nesting/disabled guard, release stores and acq_rel fence; imbalance abort. `src/store/flatstore.h:634`, `src/store/flatstore.h:2930`, `src/store/flatstore.h:2932`, `src/store/flatstore.h:2937` |
| `ForeignReadKeyGuard` | Borrows store/hash; symmetric filter references, table-bracket publication, inactive/move behaviour. `src/store/flatstore.h:657`, `src/store/flatstore.h:873`, `src/store/flatstore.h:885` |
| `ForeignReadPoisonGuard` | Whole-shard exclusion borrows store; symmetric poison scope; disabled and move behaviour. `src/store/flatstore.h:682`, `src/store/flatstore.h:2947`, `src/store/flatstore.h:2949`, `src/store/foreign_read_safety.h:98` |
| `read_local_prefetch_capture` | ExLoopT foreign capture under QSBR; acquire loads, one attempt, Churn/AtomicPending, no retirement. `src/store/flatstore.h:944`, `src/store/flatstore.h:2903`, `src/core/ex_loop.h:1158`, `src/core/ex_loop.h:1440` |
| `insert` | Matching key/hash and pre-image precondition; ownership on success; failures retain incoming object but eviction can precede refusal. `src/store/flatstore.h:1789`, `src/store/flatstore.h:2616`, `src/store/flatstore.h:2842`, `src/cmd/t_string.cc:163` |
| `SnapshotRecordState` | Owns header/progress, borrows serializer object; failure and pause state. `src/store/flatstore.h:2115`, `src/store/flatstore.h:2169`, `src/store/flatstore.h:2146`, `src/store/flatstore.h:1142` |
| `snapshot_progress_record` | Owner continuation, stable borrowed object, saved offsets, chunk/budget pause, hook/OOM failure, completion mark/cursor. `src/store/flatstore.h:2199`, `src/store/flatstore.h:1163`, `src/core/ex_loop.h:2275` |
| `Borrow` | Owner registry retains displaced object until final IO release; plain refcount has no atomic publication. `src/store/flatstore.h:2272`, `src/store/flatstore.h:1395`, `src/store/flatstore.h:1411`, `src/store/flatstore_impl.h:913`, `src/core/ex_loop.h:2018` |
| `choose_victim` | Bounded stack sample, protected/pending exclusion, borrowed pointer, LFU aging and pre-delete notification; callback limits stated. `src/store/flatstore.h:2520`, `src/store/flatstore.h:1568`, `src/cmd/eviction.cc:12`, `src/store/flatstore_atomic.inc:648` |
| `snapshot_progress_record_read_local` | Armed serialization with identical failure/pressure protocol and release mark publication. `src/store/flatstore.h:2835`, `src/store/flatstore.h:2829`, `src/store/flatstore.h:2901` |
| `choose_victim_read_local` | Same sampling constraints, relaxed-load/release-store metadata publication, notification callback limits. `src/store/flatstore.h:2860`, `src/store/kvobj.h:123`, `src/store/flatstore.h:2520` |
| `ObjectSizeTracker` | Borrows store/object; finish reports delta once, finish before erase, cancel suppresses later access. `src/store/flatstore.h:3151`, `src/store/flatstore.h:1246`, `src/cmd/t_list.cc:78`, `src/cmd/t_hash.cc:912` |
| `atomic_tombstone_all` | Owner scatter/transaction clear, cancellation before fallible preparation, bound ticket, retained predecessors and restored context. `src/store/flatstore_atomic.inc:895`, `src/cmd/scatter_engine.inc:3632`, `src/cmd/multi.inc:4121`, `src/store/flatstore_atomic.inc:758` |
| `PreparedClear` | Temporary key ownership and unlinked handle cleanup/installation transfer. `src/store/flatstore_atomic.inc:912`, `src/store/flatstore_atomic.inc:930`, `src/store/flatstore_atomic.inc:935` |
| `atomic_resolve_internal` | Borrowed winner at caller read cut/context; acquire decision loads, private overlay, null expiry, gated diagnostic poll. `src/store/flatstore_atomic.inc:1300`, `src/store/flatstore_atomic.inc:467`, `src/store/atomic_mvcc.h:234`, `src/store/flush.cc:326` |
| `atomic_exchange_physical_read_local` | Owner capacity/exclusion preconditions, transfer of replacement/displaced pointer, release stores/topology bracket, abort on capacity mismatch. `src/store/flatstore_atomic.inc:1495`, `src/store/flatstore_atomic.inc:999`, `src/store/flatstore_atomic.inc:995`, `src/store/flatstore.h:2901` |
| `atomic_exchange_physical` | Owner exchange, caller-owned predecessor, folded insertion probe, missing-delete null and capacity abort; armed delegation. `src/store/flatstore_atomic.inc:1577`, `src/store/flatstore_atomic.inc:533`, `src/store/flatstore_atomic.inc:758`, `src/store/flatstore_atomic.inc:1819` |
| `atomic_collapse_impl` | Owner/post-join cleanup; reader floor/cutoff and snapshot gate, preflight failures, release group pins after filter closure, QSBR wait and unbounded work. `src/store/flatstore_atomic.inc:1819`, `src/store/flatstore_atomic.inc:1773`, `src/store/flatstore_atomic.inc:2213`, `src/store/flush.cc:68`, `src/core/read_local.h:320` |
| `RandomKeyCursor` | Request-owned key reservoir, GroupAux retention across owner turns. `src/store/flatstore_random.inc:7`, `src/cmd/scatter_engine.inc:162`, `src/cmd/randomkey.inc:43` |
| `random_live` | Owner sampling at bound cut, 64-slot attempt, resumable home scan plus MVCC side keys; done/retry/throw and clock restoration. `src/store/flatstore_random.inc:21`, `src/cmd/scatter_engine.inc:3787`, `src/store/flatstore.h:1993`, `src/store/flatstore_atomic.inc:828` |
| `ClockGuard` | Borrowed clock restored on ordinary/exceptional scope exit. `src/store/flatstore_random.inc:24`, `src/store/flatstore_random.inc:29` |

### A19 proposals (not implemented)

| Current identifier | Proposed name | Reason / coordination |
|---|---|---|
| `tab_`, `cap_`, `mask_` | `tables_`, `capacities_`, `slot_masks_` | Distinguish table metadata; coordinate layout assertions and source controls. |
| `borrow_idx_` | `borrow_slot_index_` | Makes its pointer-to-vector-slot mapping explicit. |
| `snapshot_pos_` | `snapshot_slot_cursor_` | Separates physical traversal from the chunk sequence. |
| `read_local_pending_witness_open/close` | `read_local_pending_ref_acquire/release` | These maintain real pending references, beyond diagnostic witnessing. |
| `atomic_gauge_sub` | `subtract_version_bytes_clamped` | Names the accounted quantity and underflow behaviour. |

### Interface-first candidate — kept

**One FlatStore split kept, none reverted.** `flatstore_impl.h` is included immediately
after the class, within the same namespace/TUs. It holds the eligible private suffix:
**60 definitions / 6,809 body tokens / 943 original body lines**, in their original order.
Earlier bodies stay in-class: moving them past the path-bound `configure_object_idle`,
`make_word`, `deadline_elapsed` and `live_or_expire` definitions would violate either
source-tool paths or definition order. `flatstore_atomic.inc` also remains at its fixed
include point for lottery instrumentation. This is therefore a partial interface split.

The new header is added to A2's formatter manifest (419 maintained files). The two long
moved functions repeat their contracts above the definitions; the contract count counts
these scopes once. No body tokens change during extraction. Static qualifiers/defaults
stay on declarations, implicit in-class inline becomes explicit inline, and nested
return types/member names acquire the required FlatStore qualification. An initial
compile rejected two misplaced standard attributes in the extraction script; attribute
placement was corrected before comparison. GCC also warned when the `noinline`
`expire_found` declaration was followed by an explicit-inline definition. Its declaration
now carries both `noinline` and `inline`, which the definition inherits without repeating
them. The initial unit-build pass was stopped for this correction and restarted.
No compiler flags or budgets were changed.

```text
IDENTICAL (11167504 bytes after stripping)
```

[Class-by-class binary comparison](docs/readability-a8/evidence/split-binary.log),
[declaration correction comparison](docs/readability-a8/evidence/split-declaration-binary.log),
[moved-body comparison](docs/readability-a8/evidence/split-bodies.json).

### Binary and source proof

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 28-55 make -j28 all
taskset -c 28-55 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
taskset -c 28-55 python3 docs/readability-a8/prove_source.py
```

The [source proof](docs/readability-a8/prove_source.py) checks all **42,442 original
preprocessing tokens** against both lane base and frozen release, reversing only the
seven scoped local renames and the explicitly permitted step-6 extraction. Raw per-file
token equality is not claimed for an interface split: declarations, inline qualification
and the new include are structural tokens. The proof verifies each of the 60 transformed
signatures, exact declaration inventory and immediate include seam, then restores each
body to its declaration for the per-original-file comparison. All **25 original literal
tokens** retain their bytes; the only additional literal is the verified include filename.
Tool comments retain exact bytes and original token boundaries. No tool-bound function
moves. [Machine-readable receipt](docs/readability-a8/evidence/source.json).

Both the documentation-only build and retained split match the frozen binary.
`make format`, `make format-check`, `all` and `make -q all` pass. Final production-unit
build/freshness and selected gate jobs are in progress; results follow below.
