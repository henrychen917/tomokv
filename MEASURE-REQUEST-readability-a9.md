## readability-a9

Lane `cx-readability-a9`, base `7595a6705ac19c1a4eecf7798fde594332f0be0c`.
Frozen binary/source PRE: `5c3631281815c1652b3894d1736840c8466a5015`.
Only the 20 assigned source files changed; retained edits are comments and
formatter output. No code tokens, literals, tool markers, external names,
layouts, includes or definition order change. No push.

### Result and scope

The final comment-and-contract build passes the prescribed frozen-binary comparison:

```
IDENTICAL (11167504 bytes after stripping)
```

The [final comparison output](docs/readability-a9/evidence/binary-neutral-final.log)
is archived. The selected gate run finished with **34 passed, 0 failed**.
The PRE executable was not rebuilt. The lane makes no throughput claim and
requests no measurement. Historical figures extracted from source are explicitly
archived observations in [the decision log](docs/decisions/readability-a9.md).

| Deliverable | Count |
|---|---:|
| Original comment groups rewritten or moved into the decision log | 102 |
| New comment groups at previously undocumented token boundaries | 37 |
| Full function/type contracts added or expanded | 38 |
| Additional short ownership/borrowing notes for nested or scratch records | 13 |
| Phase landmarks inside `atomic_resolve_range` | 4 |
| Owned files with file headers | 20 / 20 |
| Local/parameter/internal-linkage renames | 0 |
| Interface-first splits kept / reverted | 0 / 1 |

A comment group is all non-tool comments at one preprocessing-token boundary;
whitespace-only reflow does not count. Contracts can expand an existing group,
so these categories overlap. [Counts](docs/readability-a9/evidence/comment-counts.json)
and [the counter](docs/readability-a9/summarize_comments.py) make the definition
reproducible. All five functions over 50 token-bearing lines have contracts:
`grisu2_digits` (66), `redis_double_text` (80), `Topology::declare` (52),
`atomic_flush_erase` (63), and `atomic_resolve_range` (134). The latter is also
the sole function over 150 physical lines and carries the four landmarks.
[The function inventory](docs/readability-a9/evidence/function-inventory.json)
records their source locations and line counts.

### Interface-first disposition

`Compact` is the only eligible class; its function inventory contains 384
token-bearing lines including the nested Iterator. Forty direct member bodies
were moved, unchanged and in order, into a topic header immediately after the
class. The nested Iterator stayed in place. The candidate built and also reported
`IDENTICAL (11167504 bytes after stripping)`.

The literal per-file token requirement cannot simultaneously accept the new
declarations and qualified out-of-class definitions. No exception is assumed:
the split was reverted to preserve that stronger proof. This was not a binary
failure. The [candidate patch](docs/readability-a9/evidence/compact-split.patch),
[40 body hashes](docs/readability-a9/evidence/compact-split-bodies.json), and
[binary output](docs/readability-a9/evidence/binary-neutral-compact-split.log)
are available for a separately approved source-token exception. The retained
source contains no new topic header.

### Source and binary proof

[Source proof](docs/readability-a9/evidence/source-identity.json) compares raw
`tools/source_tokens.py` preprocessing tokens and literal bytes for each edited
file against both lane base and frozen PRE: **20/20 exact**, with an empty rename
table. Every tool marker also has identical text and token boundary against the
lane base. Markers introduced by A1 postdate frozen PRE; they are not incorrectly
required to exist in PRE. No generated R7 block is changed.

Reproduction:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 56-83 make -j28 all
taskset -c 56-83 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
taskset -c 56-83 python3 docs/readability-a9/verify_source.py
taskset -c 56-83 make format
taskset -c 56-83 make format-check
```

The pinned formatter is clang-format 18.1.8 with the repository configuration;
its full manifest contains 418 files. Formatting and format-check precede every
commit; [the final formatter record](docs/readability-a9/evidence/format-final.json)
captures both successful commands. Only owned source paths are in the retained diff. The binary comparison
uses the supplied script's stripping rules; unstripped DWARF is not asserted
identical after comment/line changes.

### Required checks and build freshness

Selected jobs use the gate's own interface, with `LC_ALL=C`, CPUs 56–83, two
8-server-core slots at ratio 6:2 and 16 shards, driver CPUs 80–83, ports
25300–25398 and the scheduler fixture port 25399. The initial attempt explicitly
selected `production_units`; the interface rejected it as a build-only helper
before running jobs. The consuming `atomic_units` job selects it automatically:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
export GATE_PROOF_NO_RATES=1 GATE_TEST_PORT=25399
export GATE_ONLY_JOBS='source_identity reorder_sync reorder_identity atomic_units flushfix3_units abba_selftest'
taskset -c 56-83 tests/gate.sh quick \
  --server-cores 56-79 --load-cores 80-83 --load-smt '' --ports 25300-25398
```

All selected jobs completed successfully (gate process exit 0):

| Job | Result |
|---|---|
| `release` | 1 passing row; production build and footprint locks |
| `production_units` | Build-only prerequisite; all 65 readiness markers present |
| `source_identity` | 1 passing row; source identity and stable assertion IDs |
| `abba_selftest` | 1 passing row; includes `gates_test.py` (83 tests) and the label fixture (12 tests), both OK |
| `flushfix3_units` | 2 passing rows; ordinary and DB-0 units plus historical-work negative controls |
| `reorder_sync` | 1 passing row; R7 generator, lexer/anchor and lottery fixtures |
| `reorder_identity` | 1 passing row; 352/352 ordinary bodies identical and six negative controls rejected |
| `atomic_units` | 27 passing rows, including both FLUSH/header text-reader controls |

[The selected-job record](docs/readability-a9/evidence/selected-jobs.json),
[gate transcript](docs/readability-a9/evidence/gate-final.log),
[ledger](docs/readability-a9/evidence/gate-ledger.tsv), and
[fixture output](docs/readability-a9/evidence/gate-fixtures.log) retain the results.
The raw run directory is `build/gate-run.5Cfo4M`.

Every one of the 61 primary `job_production_units` targets built, as did `all`,
both `mdbqsbr` diagnostic images, `blockfix-cost` and its checksum, and both
`blockfix2` units. All corresponding freshness queries pass, including default
`make -q`. The recipe-only `mdbqsbr-live-arms` wrapper is checked through the two
recursive `all` targets it invokes. The two `flushfix3` unit targets also pass
freshness checks. See [the target inventory](docs/readability-a9/evidence/production-targets.json)
and [commands/results](docs/readability-a9/evidence/build-freshness.json).

The A1 LIVE text-reader mapping is:

| Reader | Coverage |
|---|---|
| `tools/source_identity.py`, `tools/assert_map.py`, `tests/tomo_assert_checks.py` | `source_identity` and the release assertion-map build |
| `tools/source_tokens.py`, marker manifest and lexer/anchor fixtures | direct exact-token proof plus `reorder_sync` |
| `tests/r7shadow_sync.py`, its fixtures, `tools/reorder_sync.py`, lottery source preparation/negative controls | `reorder_sync` |
| R7 FIFO/off-path identity and missing-symbol controls | `reorder_identity` |
| `tests/flushfix_checks.py`, six constructor/header mutation sites | `atomic_units` and its `production_units` build dependency |
| `tools/flushfix3_work_reference.py`, current FLUSH body anchor and bounded historical-work negative control | `flushfix3_units`, ordinary and DB-0 images |
| `tests/gate.sh` job source/label extraction, `tests/gates_test.py`, `tests/gate_ledger_fixture.py` | `abba_selftest`; the label unittest is reached by `gate_receipt.py --self-test` |
| `tools/ttlstate_proof.py` | Its currently live importer uses the ELF `program_headers` helper, not source matching. An additional direct call to its unchanged `source(root, 'absent')` checked 1,486 text files and found zero retired-type/accessor hits. |

The ttlstate CLI itself is **NOT RUN**: it hard-codes CPUs 112–127, outside this
lane's allocation. Its source function was imported under `taskset -c 56-83`
without changing the tool. No active gate job calls that source inventory;
[the result](docs/readability-a9/evidence/ttlstate-source.json) is supplemental.

The full `iteration` and `full` gates, benchmarks, ABBA rates and NIC measurements are
**NOT RUN**, as assigned to the maintainer. No new or retired gate row;
`EXPECT_QUICK=1212` and `EXPECT_FULL=1229` remain unchanged, with no count update
requested. The complete label fixture is unchanged. This selected-job run is
not a full-gate receipt.

### A19 rename proposals

No rename is applied by this lane. These names are visible outside A9 and need
cross-tree callsite/tool review by A19:

| Existing name | Proposed name | Reason |
|---|---|---|
| `Terminated` | `NullTerminatedArgument` | Names the owned numeric-argument copy and its terminator. |
| `KvObj::raw_length_relaxed`, `store_raw_length_relaxed` | `raw_length`, `store_raw_length` | Their bodies use plain `vlen` accesses; “relaxed” suggests an atomic operation they do not perform. |
| `KvObj::vlen` | `value_storage_length` | Represents raw/external string length or compact tail allocation length, rather than one universal logical value length. |
| `AtomicPendingState::live` | `linked_record_count` | Counts linked MVCC records, not resident keys. |
| `UnitRef` | `AtomicUnitRef` | Identifies the borrowed transaction/group decision prefix. |

### Contract evidence

Whole-tree caller searches covered ordinary dispatch, generated R7 blocks,
commands, persistence and fixtures before assigning roles. The contracts below
state caller obligations where the type has no enforcement mechanism. No new
configuration mutability claim is made. Class contracts cover the short member
functions and their representation/lifetime obligations; the five long functions
also have direct contracts.

| Contract(s) | Code evidence and limits |
|---|---|
| `grisu2_digits` (`src/base/numeric.h:177`); `redis_double_text` (`src/base/numeric.h:294`) | Special-value handling precedes positive finite digit generation; local arithmetic and caller buffers perform the work. Formatting returns a length, does not terminate or check cap, and allocates no shared state. Callers provide the stated fixed buffers. Evidence: `src/base/numeric.h:295`, `src/base/numeric.h:336`, `src/net/resp.h:939`, `src/net/resp3.h:86`, `src/cmd/scripting.cc:945`. |
| `Terminated` (`src/base/numeric.h:390`) | The constructor copies into its 256-byte array or owned string, then stores a pointer into that storage. No copy rebasing, allocation catch or publication is implemented; parsers use stack instances and borrow get(). Evidence: `src/base/numeric.h:392`, `src/base/numeric.h:420`, `src/cmd/t_server.cc:3901`. |
| `Slice` (`src/base/slice.h:117`); `SmallBuf` (`src/base/slice.h:194`) | Slice stores a borrowed pointer/length/namespace. Key equality adds identity; value equality ignores namespace. SmallBuf owns inline/malloc storage and frees growth, but plain size changes provide no publication. Growth has no malloc-failure/overflow handling; direct commits and input lifetimes require caller discipline. Conn and WbEngine both commit bytes. Evidence: `src/base/slice.h:165`, `src/base/slice.h:267`, `src/net/conn.h:477`, `src/net/wb.h:862`, `src/exec/op.h:152`. |
| `Topology` (`src/base/topology.h:40`); `Topology::declare` (`src/base/topology.h:50`) | Boot preparation and fixtures populate plain vectors. Declaration checks affinity, duplicates and syntax but can leave partial state; discovery has per-CPU fallback and sibling discovery requires sysfs. Queries require serialized mutation and valid cpus_in indices; vector exceptions are uncaught. Evidence: `src/core/server.h:287`, `src/base/topology.h:54`, `src/base/topology.h:131`, `tests/config_parser_test.cc:130`. |
| `AtomicEntry` (`src/store/atomic_mvcc.h:24`) | Preparation allocates the trailing slots/key tail; installation bounds count by capacity. FlatStore links and retires records and balances retained group state, including shutdown. Group decisions use acquire loads; plain lists do not publish across threads. Evidence: `src/store/flatstore_atomic.inc:491`, `src/store/flatstore_atomic.inc:539`, `src/store/flatstore_atomic.inc:1263`, `src/store/flatstore_atomic.inc:2217`, `src/store/atomic_mvcc.h:253`. |
| `AtomicScriptIntent` (`src/store/atomic_mvcc.h:83`); `UnitRef` (`src/store/atomic_mvcc.h:104`) | PINs own copied keys; unit-intent allocations prefix UnitRef while kind-0 pins do not. Plain refs/links require owner serialization; activity transitions use release RMWs. Allocation failure is reported by pin helpers. Command code retains decision targets, and group-unit destruction releases watch_refs. Evidence: `src/store/flatstore_atomic.inc:143`, `src/store/flatstore_atomic.inc:175`, `src/store/flatstore_atomic.inc:217`, `src/store/flatstore_atomic.inc:250`, `src/cmd/txn_group.inc:573`. |
| `AtomicPendingState` (`src/store/atomic_mvcc.h:132`); `AtomicPendingState::FreeValue` (`src/store/atomic_mvcc.h:134`) | The store owns lazy state, intrusive pools and plain counters. Extension initializes the discriminator before arming; combined finish-install touches only the installing/group-count bytes. FreeValue overlays dead value storage. Allocator failures belong to the prepare helpers; shutdown releases state. Evidence: `src/store/flatstore_atomic.inc:1096`, `src/store/flatstore_atomic.inc:1135`, `src/store/flatstore_atomic.inc:1149`, `src/store/flatstore_atomic.inc:1172`, `src/store/atomic_mvcc.h:166`. |
| `AtomicFlushCounters` (`src/store/atomic_mvcc.h:191`) | Both decision and owner paths update relaxed atomic counters and INFO samples them. The inline global is separately compiled per namespace and cannot provide a coherent multi-field publication snapshot. Evidence: `src/cmd/flush.inc:154`, `src/store/flush.cc:430`, `src/cmd/t_server.cc:3391`. |
| `AtomicResolved` (`src/store/atomic_mvcc.h:207`); `AtomicCollapseKey` (`src/store/atomic_mvcc.h:216`); `AtomicCollapseSlot` (`src/store/atomic_mvcc.h:238`); `AtomicSeenKey` (`src/store/atomic_mvcc.h:244`) | Resolver results and collapse/seen-key scratch borrow objects, records and key bytes; the owning traversal transfers/retires them. Scratch indices use index+1 with zero empty; these aggregates have no independent lifetime or publication operation. Evidence: `src/store/flatstore_atomic.inc:1302`, `src/store/flatstore_atomic.inc:1822`, `src/store/flatstore_atomic.inc:838`. |
| `atomic_install_flush` (`src/store/flush.cc:19`); `atomic_flush_release` (`src/store/flush.cc:49`) | execute_flush installs on the owner and handles null as OOM before linking. Poison precedes range linkage; release unlinks, recounts saturated ranges, closes poison and release-decrements refs/activity. Invalid release input aborts; shutdown also releases ranges after joining. Evidence: `src/cmd/flush.inc:87`, `src/store/flatstore_atomic.inc:1263`, `src/store/flatstore_atomic.inc:2217`. |
| `FlushPostIndex` (`src/store/flush.cc:119`); `FlushPostIndex::Slot` (`src/store/flush.cc:121`) | Local vectors own scratch; slots borrow stable key storage and parked-slot addresses. Sixteen hash probes fall back to increasing-bit Patricia descent, using 64 hash bits, eight namespace bits and nine per key byte. First insertion wins; allocation exceptions are caught before mutation by atomic_flush_erase. Evidence: `src/store/flush.cc:139`, `src/store/flush.cc:173`, `src/store/flush.cc:217`, `src/store/flush.cc:276`. |
| `atomic_flush_erase` (`src/store/flush.cc:261`) | The owner admits a ready range after snapshot preservation. Scratch capacity/allocation refusal returns false before changing residents; execute_flush defers it. Erasure releases tombstones before deferred retirement, clears first-post predecessor slots, and preserves unarmed send-borrow retirement. The deferred queue supplies writer back-pressure. Evidence: `src/cmd/flush.inc:124`, `src/store/flush.cc:273`, `src/store/flush.cc:286`, `src/store/flatstore.h:3529`, `src/store/flatstore.h:3447`, `src/store/flatstore.h:3766`. |
| `atomic_resolve_range` (`src/store/flush.cc:351`) | Owner-local resolution returns borrowed physical/parked state with acquire group decisions. Same-connection floors precede visibility filtering and own epoch-zero values rank first. There is no allocation or ordinary wait; the armed diagnostic alone re-polls at most 4096 times and does not replace the selected answer. Evidence: `src/store/flatstore_atomic.inc:1302`, `src/store/flatstore_atomic.inc:1297`, `src/store/atomic_mvcc.h:253`, `src/store/flush.cc:371`, `src/store/flush.cc:505`. |
| `ForeignReadSafety` (`src/store/foreign_read_safety.h:29`) | The shard owner publishes before mutation and closes after safety; readers acquire cell/epoch words. Cells are release-stored before release epochs. Saturation stays positive until exact drain; total/nesting overflow poisons permanently and detected underflows abort. uint32_t epoch increment can wrap; no suspension bound is established. Evidence: `src/store/flatstore.h:882`, `src/store/flatstore.h:3678`, `src/store/flatstore.h:3722`, `src/store/foreign_read_safety.h:195`, `src/store/foreign_read_safety.h:230`, `src/store/foreign_read_safety.h:270`. |
| `KvBlockCache` (`src/store/kv_block_cache.h:45`) | Per-physical-owner plain lists reuse post-grace blocks; migration changes future sink/cache access. put rejection retains caller ownership; take transfers a block or misses. Capacity checks and detected corruption are explicit, with a relaxed INFO byte gauge. Shutdown after joins also drains; the aggregate itself has no destructor cleanup. Evidence: `src/store/flatstore_atomic.inc:1684`, `src/store/flatstore_atomic.inc:1705`, `src/core/read_local.h:351`, `src/core/server.h:2158`, `src/store/kv_block_cache.h:196`, `src/store/kv_block_cache.h:222`. |
| `KvObjFlagByte` (`src/store/kvobj.h:69`); `KvObj` (`src/store/kvobj.h:99`) | Flag accesses are atomic but compound operators are load/store pairs, not RMWs. Foreign eviction CAS is unretried and approximate; immutable published string layout/content depends on caller replacement/QSBR. Header/tail accessors borrow storage and assume correct encoding/capacity; OwnsExtern selects destruction. Evidence: `src/store/kvobj.h:77`, `src/store/kvobj.h:136`, `src/store/kvobj.h:1209`, `src/store/flatstore.h:2942`, `src/store/flatstore.h:3395`. |
| `EmbeddedCompact` (`src/store/kvobj.h:304`) | The object tail owns metadata and subsequent packed bytes; memcpy handles unaligned fields. No destructor/allocation/publication/bounds checks exist in the overlay. Constructor/adopt helpers populate aux fields for hash, set or stream and leave list/zset aux values zero. Evidence: `src/store/kvobj.h:327`, `src/store/kvobj.h:333`, `src/store/kvobj.h:963`, `src/store/kvobj.h:1090`. |
| `CompactView` (`src/store/kvobj.h:367`); `CompactView::Iterator` (`src/store/kvobj.h:373`); `CollectionRef` (`src/store/kvobj.h:646`) | Views/iterators borrow embedded or external storage, without publication/lifetime retention. Default views require binding and current positions. Embedded mutations validate boundaries/capacity and do not allocate; external ones delegate. CollectionRef guards compact mutation by encoding, but compact/aux access has representation preconditions. Inputs must survive mutation. Evidence: `src/store/kvobj.h:612`, `src/store/kvobj.h:475`, `src/store/kvobj.h:648`, `src/cmd/t_list.cc:231`, `src/cmd/t_set.cc:285`. |
| `KvObjRawReadBuffer` (`src/store/kvobj.h:819`); `kvobj_init_raw_string` (`src/store/kvobj.h:832`) | The scratch parameter is unused by string_value, which borrows object bytes. Raw initialization fills caller memory, rejects null/over-threshold inputs and allocates nothing. Factory and cached-block callers establish storage size and later publication; key/value sources must not overlap writes. Evidence: `src/store/kvobj.h:823`, `src/store/kvobj.h:880`, `src/store/flatstore.h:1367`. |
| `ObjectIdleClock` (`src/store/object_idle.h:16`); `ObjectIdleClock::Branch` (`src/store/object_idle.h:18`) | Install release-publishes fixed links and accounts nodes incrementally; false retains partial nodes. cell acquires links; timestamps use relaxed operations and one strong CAS attempt. Store configuration publishes/retires clocks; reclamation or quiescent teardown permits recursive node destruction. Missing cells/timestamps fall back. Evidence: `src/store/object_idle.h:48`, `src/store/object_idle.h:75`, `src/store/object_idle.h:107`, `src/store/flatstore.h:1549`, `src/store/flatstore.h:1539`. |
| `ReadLocalRetireSink` (`src/store/read_local_reclaim.h:29`); `ResizeRetirement` (`src/store/resize_retirement.h:14`); `ResizeRetireQueue` (`src/store/resize_retirement.h:25`) | The sink borrows queue/cache/context until callbacks finish, forwards without validation, and the real queue can wait for ring space. seq_cst epoch RMW plus grace floor is outside these helpers. Resize records are preallocated, transfer table ownership to a FIFO and free it on pop; stamps must be ordered, and unconditional drains/destruction need quiescence. Evidence: `src/core/read_local.h:267`, `src/core/read_local.h:301`, `src/core/read_local.h:351`, `src/core/server.h:801`, `src/store/flatstore.h:3514`, `src/store/resize_retirement.h:44`. |
| `Compact` (`src/store/typeval.h:79`); `Compact::Entry` (`src/store/typeval.h:83`); `Compact::Iterator` (`src/store/typeval.h:92`) | Vectors own encoded storage and the optional circular index; entry/iterator views borrow it. Index allocation starts above 16 entries. Growth may relocate before a later failure; spans and source lifetimes are caller preconditions. Guarded allocation/bounds failures return false, while generated vector copying can throw. No synchronization is implemented. Evidence: `src/store/typeval.h:424`, `src/store/typeval.h:380`, `src/store/typeval.h:202`, `src/store/typeval.h:495`, `src/store/typeval.h:344`. |
| `CompactValue` (`src/store/typeval.h:564`) | The base owns Compact and counters; derived structures own expanded data. Promotion records totals before clearing Compact, requiring prior copies in the destination. Guarded methods refuse expanded values; no demotion method, publication or wait exists here. Evidence: `src/store/typeval.h:624`, `src/store/typeval.h:646`, `src/store/typeval.h:607`, `src/cmd/t_stream.cc:774`. |
| `HashVal` (`src/store/typeval.h:700`); `ListNode` (`src/store/typeval.h:725`); `ListVal` (`src/store/typeval.h:734`) | Hash destruction deletes field map and TTL side state; hash helpers maintain separate logical/TTL totals. Each ListNode owns Compact and borrows chain links; ListVal deletes its chain. Handlers build/attach nodes and serialize resident mutations; wrappers supply no publication. Evidence: `src/cmd/t_hash.cc:460`, `src/store/typeval.h:738`, `src/cmd/t_list.cc:161`, `src/cmd/t_hash.cc:1686`. |
| `StreamNode` (`src/store/typeval.h:754`); `StreamVal` (`src/store/typeval.h:774`) | Deque nodes own their packed logs, whose first entry carries the header. StreamVal owns nodes, indices/dictionaries and opaque groups; its destructor releases groups. Stream handlers construct/mutate and maintain totals; borrowed node storage requires caller lifetime protection. Evidence: `src/cmd/t_stream_groups.cc:1586`, `src/store/typeval.h:782`, `src/cmd/t_stream.cc:774`. |
| `SetMemberTable` (`src/store/typeval.h:805`); `SetMemberTable::Slot` (`src/store/typeval.h:835`); `SetVal` (`src/store/typeval.h:866`); `ZsetVal` (`src/store/typeval.h:881`) | Set slots own strings; the table owns slots and dense indices. Rebuild changes generation, erase leaves tombs, and borrowed values can expire. Insert/reserve distinguish checked refusal/OOM. Set promotion uses logical integer payload totals; ZsetVal deletes its expanded pointer. Resident mutation is caller-serialized with no wrapper publication. Evidence: `src/cmd/t_set.cc:44`, `src/cmd/t_set.cc:132`, `src/cmd/t_set.cc:164`, `src/store/typeval.h:867`, `src/cmd/t_zset.cc:849`. |

### Limits and pre-existing hazards made explicit

- `ForeignReadSafety` epochs wrap at 32 bits. A maximum reader suspension is not
  established by the counter/caller code inspected; equal epoch samples alone
  do not prove the bucket was untouched. Other store-generation/poison checks
  remain in place. This is a proof limitation, not a demonstrated torn read;
  no synchronization or correctness law was weakened.
- `SmallBuf` does not handle malloc failure or arithmetic overflow, and its
  reserve/advance/commit operations rely on caller bounds. The documented failure
  behavior is the existing implementation, not a new graceful-OOM claim.
- Copying `Terminated` does not rebase its internal pointer. Inspected production
  callers construct local instances; the type's copy/lifetime hazard is documented
  rather than silently hidden by an ownership claim.
- Topology parse failures and idle-clock installation failures can leave partial
  state. The clock retains/account-charges installed nodes; topology callers
  reject unsuccessful preparation.

The split experiment's saved header and the R7 scratch FIFO binary were removed
after their proofs completed. Build targets and generated prerequisites remain
available for freshness checks. [Cleanup evidence](docs/readability-a9/evidence/cleanup.json)
records a final worktree size of 25.46 GB, below the 30 GB limit. No added or
modified committed file exceeds 1 MB. The report, decision log and proofs are
committed on `cx-readability-a9`; no push or merge is performed.
