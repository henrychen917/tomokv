# multidb lane: implementation, remaining gaps, and measurement request

Worktree: `/home/user/Projects/cx-multidb`; branch: `cx-multidb`.
PRE: `115da1721` (the supplied `84846e904` baseline plus reference rebaseline).
POST implementation: `6b9bbcacd`, including its preceding multidb commits.

**Not merge-ready.** The implemented surface and serverless checks below are committed, but
the following scope gaps remain. No server, gate, benchmark, load generator, or live oracle was
started or contacted by this lane. Builds and executable unit checks were pinned to CPUs 112–127.

1. **SWAPDB versus other clients' in-flight writes needs a stronger mapping boundary.** Its
   current all-shard rendezvous publishes one immutable map pointer, serializes concurrent swaps,
   waits out snapshots, and preserves this connection's pipeline order. It does not drain other
   connections' already-stamped requests. A schedule permitted by the code is: connection A
   stamps `SET k v` in physical namespace 0 and is delayed; B completes `SWAPDB 0 1`, then reads
   missing `k` in logical DB 1; A subsequently executes its old stamp into physical namespace 0
   (now logical DB 1). Final reads see `k` in DB 1, not DB 0. Those observations have no Redis
   serial ordering. This is a code-review counterexample, not a network result. The existing
   per-connection ROB barrier does not provide the required global boundary. Freezing owner
   inboxes at a rendezvous also permits deadlock with unfinished multi-owner transactions, so
   this candidate uses nonblocking owner deferral instead. That fixes rendezvous liveness but
   does not solve this namespace-ordering gap. Do not infer concurrent-write SWAPDB correctness
   from the concurrent-read battery.
2. **SWAPDB inside MULTI/EXEC is still unsupported.** It queues, then returns the existing
   unsupported-command error as its EXEC array element. Publishing a map independently of the
   transaction's MVCC decision would expose a torn transaction. SELECT and MOVE in EXEC are
   implemented. Existing EXEC restrictions on FLUSHDB/FLUSHALL/RANDOMKEY remain.
3. **Persistence is native TomoKV persistence, not Redis file interoperability.** The baseline
   saves `TOMOSNP`/`RECD` snapshots and `TOMOAOF`/`AORC` journals, not Redis RDB opcode streams or
   RESP AOF command streams. This patch adds namespaces and map records to those actual formats.
   Literal Redis RDB SELECT opcodes and RESP AOF SELECT records are not implemented.
4. **The configured maximum is 256 databases.** Default 16, the `databases N` spelling, boot-only
   behavior and SELECT bounds follow the requested interface. Redis's larger configured counts
   are not supported: a one-byte namespace cannot represent more than 256 distinct live
   keyspaces. Supporting Redis's full configuration range requires changing that design choice.
5. **Zero db-0 cost remains unproved.** No rates, retired instructions, cycles or IPC were measured.
   The branch must not land on the static observations below alone.

## Implemented representation and routing

`src/cmd/multidb.cc` is the feature implementation; store, scheduler, command and persistence
files carry the necessary integration. There is one shared sharded store, not N stores.

* `Slice` remains 16 bytes. Its former four padding bytes hold namespace identity. Key equality
  compares `(length, namespace, bytes)`; value/member/field equality remains byte equality.
* The default routing hash folds the namespace into its existing initial multiplication. With
  namespace zero, the hash expression produces the baseline hash. The optional SipHash path
  folds namespace identity after hashing; it has additional arithmetic and is not a zero-cost
  claim.
* A db-0 object retains the existing eight-byte header and key/value offsets. A nonzero namespace
  uses the existing KeyExt layout: the length moves to its four-byte extension and `klen8`
  encodes namespace minus one. Existing extended db-0 keys retain `klen8 == 255`. No reserved
  key prefix is introduced; empty, binary, 254-, 255- and 256-byte keys are tested.
* `Op` uses existing padding for logical and physical database stamps and transfer destinations.
  A connection that has selected a nonzero DB remains armed, so recycled ROB slots cannot
  accidentally reuse an old database stamp after SELECT 0. A map publication also arms stamping.
* A never-switched db-0 connection before the first map publication bypasses the stamp helper.
  Parser-pass state is folded into the existing notification/observer branch; no separate db-0
  per-operation branch was added. This scope is narrower than "every operation executed in
  logical DB 0 after arbitrary SELECT/SWAPDB history is free."
* Mapping reads take a single immutable pointer with reclamation protection; there is no seqlock
  or reader retry. Mapping storage is allocated only when a map is published. The map swap is
  constant in the number of keys, but WATCH and blocked-client maintenance is not O(1).

Locked sizes checked by the unit: Op 336; Client 1984; ThreadCtx 1408; Shard 1440; FlatStore 944;
Rob<64> 192; AtomicEntry 144; Config 624.

## Parse-time SELECT and RYOW

`IoLoop::parse_and_dispatch` stamps armed operations before routing and read-local admission.
SELECT executes on its ConnLocal dispatch path and ends that parser pass. It does not drain
older ROB work. Later frames get the new logical DB; previously issued operations retain their
original physical keys. Replies still retire through the existing ROB.

During MULTI, SELECT is copied into the queue without changing the connection. EXEC captures
one mapping, computes each child's DB in queue order, and applies successful queued SELECTs
to the session at retirement. A bad index leaves the following child's DB unchanged; an aborted
WATCH transaction does not apply its SELECTs. MOVE and COPY DB lower through namespace-aware
source/destination keys. MONITOR/SLOWLOG preserve MOVE's original destination-index argument.

The RYOW identity is the composite key at all relevant points: router hash, exact store and
read-local probes, write-ring hash inputs, pending MVCC records, group duplicate detection,
script keys, derived SORT lookups, WATCH and blocking registries. Immutable replacement and
the existing QSBR reclamation remain in force when read-local is armed. No foreign-owner store
write or per-operation seqlock was added. Shard-owned metadata stays with its Shard; the mapping
contains physical namespace numbers, not owner pointers.

WATCH registers cold owner-local aliases for each configured namespace. Only the active alias
participates in ordinary validation/writer invalidation. The aliases let a swap inspect keys on
their own owners, including the case where a previously absent watched key gains a value from
the other database. Both-absent swaps preserve WATCH; existing-key swaps and swap-back dirty it.
The existing OOM regression now checks complete alias rollback, unique namespace registrations,
and reference release instead of assuming one physical registration.

The new protocol battery checks 2,048 exact SET / SELECT 1 / GET / SELECT 0 / GET cycles with
four writers using the same raw key in other databases. It requires writer progress during the
test and, with read-local enabled, a positive read-local hit-counter witness. There is no clock
tolerance change or skipped arming case.

## Command and persistence breadth

Implemented standalone surfaces: SELECT, MOVE, SWAPDB, COPY DB, namespace FLUSHDB, DBSIZE,
KEYS, SCAN, RANDOMKEY, INFO keyspace rows and CLIENT database reporting. SCAN and whole-store
walks filter namespace; expiration indexes retain composite hashes. RANDOMKEY currently gathers
matching visible keys across shards, so its cost is a store walk, not the baseline random-shard
sample. INFO's per-namespace statistics allocation occurs only for INFO requests.

Notification records carry logical DB at event creation; publication formats both keyevent and
keyspace channel numbers from that stamp. MOVE emits move_from and move_to in the appropriate
databases. Parked blocking commands detect mapping changes and re-register on the newly mapped
owners while retaining deadlines and resolved stream cursors.

Native snapshot records use a previously reserved header byte for namespace. An identity-map
snapshot retains the baseline 80-byte file header; a nonidentity map uses an extended header.
Native AOF records similarly carry namespace in reserved header space, scoped FLUSH records,
and a new map record. Loads validate configured namespace bounds. The native snapshot and AOF
replay unit checks a nonidentity map and values in multiple namespaces.

Byte-identity claim is limited to unchanged identity-map db-0 record encodings. In particular,
db-0 FLUSHDB now journals a scoped flush instead of the old FLUSHALL alias, and a logically
db-0-only dataset after a nonidentity swap can require map metadata. A blanket claim that every
db-0-only file is byte-identical to PRE is not established.

The registry has 245 commands. An offline semantic comparison against PRE checks all 372 old
COMMAND metadata entries (including subcommands), resolved tips/key specifications, and 242
existing ACL masks unchanged. Only MOVE/SWAPDB entries are added. New masks are respectively
`0x4005` (keyspace/write/fast) and `0x24005` (keyspace/write/fast/dangerous).
The pinned live-oracle generator checks remain for mainline.

Redis behavior references used to check errors/WATCH semantics:
[MOVE](https://redis.io/docs/latest/commands/move/),
[SWAPDB](https://redis.io/docs/latest/commands/swapdb/),
[Redis 7.4 database command semantics](https://raw.githubusercontent.com/redis/redis/7.4/src/db.c),
[Redis 7.4 integer argument semantics](https://raw.githubusercontent.com/redis/redis/7.4/src/object.c),
[Redis 7.4 WATCH semantics](https://raw.githubusercontent.com/redis/redis/7.4/src/multi.c).
These were read for interface behavior, not copied into the implementation.

## Gate changes and local verification

The task's explicit authorization to bump EXPECT overrides the general context prohibition.
`EXPECT_QUICK: 419 -> 428`, `EXPECT_FULL: 435 -> 444`: **+9 to both**.

* One `multidb serverless owners` row is defined at `tests/gate.sh:1297` and collected by the
  atomic-units collection at `tests/gate.sh:2672`, before the quick exit.
* Eight rows (1s/2s × read-local 0/1 × atomic 0/1) are collected at `tests/gate.sh:2773`.
  Each includes RYOW, scoped commands, queued SELECT, WATCH, sequential/concurrent-reader swaps,
  a blocked waiter, notifications and both native persistence replay paths.
* The quick-tier exit is at `tests/gate.sh:2796`. Both additions are above that line.
* `gen_multidb` joins the existing full-tier differential matrix rows; it adds no ledger row.
  It uses 512-command batches with randomized SELECT/MOVE/SWAPDB/FLUSHDB/DBSIZE/KEYS/COPY and
  SELECT inside EXEC. The existing ±1 clock tolerance is unchanged.

Completed serverless checks:

| Check | Result |
| --- | --- |
| multidb unit, including layouts and store/read-local namespace identity | PASS |
| multidb native snapshot capture and AOF namespace/map replay | PASS |
| multidb owner phases, MOVE atomic 0/1 on same/different shards, SELECT/EXEC/WATCH/INFO | PASS |
| 15 gate-listed atomic-survivor cases, including WATCH OOM sweep | PASS |
| 11 ordinary storage regressions; separately built deadline-sidecar case | PASS |
| 9 gate-listed netcmd serverless cases | PASS |
| config-parser test and read-local write-ring unit | PASS |
| Python syntax, bash syntax, differential inventory, git diff whitespace | PASS |
| namespacing-disabled copy of multidb-unit | Expected failure at exact namespace GET check |
| gate / boots / live Redis oracle / network protocol batteries / measurements | NOT RUN |

Two unsuccessful diagnostic invocations are retained in the logs. `deadline-sidecar` first
refused the ordinary build as designed, then passed in its required sidecar build. The existing
`post_apply_probe` in `atomic_survivors_unit.cc`, explicitly labelled an unresolved diagnostic
outside the green gate, still failed: both APPEND replies were `:2`, final value `BW`, with no
legal serial outcome. PRE's copy of that diagnostic was not executed, so this is not an A/B
regression classification. It remains a separate known correctness issue, not a green result.

Principal build/test/artifact commands run (all executable work pinned):

```sh
taskset -c 112-127 make -j8 build/tomokv
# PRE was copied before edits; subsequent builds used the same flags.
taskset -c 112-127 make -j8 build/multidb-unit build/tomokv build/atomic-survivors-unit
taskset -c 112-119 timeout 60 ./build/multidb-unit
taskset -c 120-127 bash -c 'for case in admission closure script_keys rename_overlay write_latest script_apply lua_conversion watch_parent watch_cycle mset_arity watch_oom lua_lines library_limit stage_flag instruction_limit; do timeout 60 ./build/atomic-survivors-unit "$case" || exit; done'
taskset -c 112-127 make -j8 build/store-regression build/read-local-write-ring-unit build/config-parser-test build/netcmd-unit
taskset -c 112-119 bash -c 'for case in unlinked randomkey rehash rollback snapshot-eviction flags aof-eviction intents imported-hash field-index-failure hash-bytes deadline-sidecar; do timeout 60 ./build/store-regression "$case" || exit; done'
taskset -c 112-127 make -j8 build/store-regression-sidecar
taskset -c 112-119 timeout 60 ./build/store-regression-sidecar deadline-sidecar
taskset -c 120-127 bash -c 'for case in streams zpop notify-oom notify-retry flush output pubsub receive config; do timeout 60 ./build/netcmd-unit "$case" || exit; done'
taskset -c 112-127 ./build/config-parser-test
taskset -c 112-127 ./build/read-local-write-ring-unit
taskset -c 112-119 python3 tests/differ.py --list-generators
bash -n tests/gate.sh
git diff --check
cp build/tomokv build/tomokv-multidb-post
taskset -c 112-127 python3 tools/multidb_artifacts.py build/tomokv-multidb-post build/tomokv-multidb-pad
taskset -c 112-127 python3 tools/multidb_artifacts.py build/multidb-unit build/multidb-unit-namespaces-off
taskset -c 112-119 timeout 60 ./build/multidb-unit-namespaces-off
sha256sum build/tomokv-multidb-pre build/tomokv-multidb-post build/tomokv-multidb-pad
```

Build and test outputs are retained as `build/multidb-*.log`; offline receipts are
`build/multidb-pad.json`, `build/multidb-unit-negative-control.json`,
`build/multidb-metadata-audit.json` and `build/multidb-code-audit.json`.
`build/multidb-atomic-gate-cases.log` contains the completed 15-case success run. The older
`multidb-atomic-regression-tail.log` retains the WATCH fixture's one-registration assertion
failure before it was updated to validate every alias; that failure is resolved.

## Cost proof requested from mainline

**PAD kind A: behaviour twin** — physical namespace identity is forced to zero, in an exact
copy of POST's text layout. `multidb_namespace(uint8_t)` is patched to `xor eax,eax; ret` without
relinking; every section size, symbol address and byte outside that three-byte patch is checked
identical. It is a namespace-disabled control, not a rollback of every administrative command.
In particular, it cannot by itself detect common overhead present in both POST and PAD.

| Arm | File | SHA-256 |
| --- | --- | --- |
| PRE | build/tomokv-multidb-pre | 8f6da00365aced98eb925906ec2dfdb2ca9cf8995a40371ad48d7dfa5ff79034 |
| POST | build/tomokv-multidb-post | 1189c0f9c6ac80ee6da9edd4250507965655c91cb7fcc2695c0b7bf3e3bfa1bd |
| PAD A | build/tomokv-multidb-pad | add43eba09bb08cef10ca1f67195bb715a0d1d64d2d681c5a5c3b5d291dc65b1 |

Final ELF `.text`: PRE 3,557,219 bytes; POST/PAD 3,547,569 bytes (POST −9,650 bytes).
The `size` utility's aggregate text figure is PRE 4,104,166; POST/PAD 4,098,038.
No inverse-control PAD B was made.

Static disassembly observations, **not retired instr/op**:

| Emitted body | PRE bytes / static instructions | POST bytes / static instructions |
| --- | --- | --- |
| cmd_get<false,true> | 1072 / 248 | 1072 / 248 |
| cmd_set<false> | 2201 / 503 | 2201 / 503 |
| cmd_get<true,false> | 776 / 167 | 792 / 169 |
| cmd_get<true,true> | 1088 / 249 | 1088 / 249 |
| cmd_set<true> | 2182 / 507 | 2182 / 506 |

The unchanged clean GET/SET body sizes/counts are useful but not a proof: hash/store callees,
parser argument initialization, register pressure and text placement also changed. No full
hot-path byte identity is claimed. No namespace map access, stamp call, or new per-operation
namespace branch is intended on the never-switched db-0 parser path. Rate at matched offered
load plus retired instr/op, cycles/op and IPC must decide whether that intention holds.

After resolving the blocking scope/correctness gaps, use the gate's existing ABBA instrument and
its matched null. Keep its geometry, population, key/value distribution, offered load, counter
windows and repeat count identical across arms. All measurement connections must remain in DB 0,
with no SELECT to another database and no SWAPDB. Measure PRE↔POST, PRE↔PAD A and POST↔PAD A.

Requested p32 headline cells: `h01,h02,h09,h10,h17,h18,h25,h26` (GET/SET, both modes, read-local
off/on, overlap/reorder off). Also retain the shipped-posture cells `h15,h16,h31,h32` and the
ordinary full gate/ABBA regression requirement. The mode/read-local/atomic correctness product
is the eight new gate rows; the headline file's atomic-1 rows do not replace atomic-0 correctness.

For each cell append a PRE/POST/PAD table with rate, retired instr/op, cycles/op and IPC, each
matched to the same offered load. Landing bar: POST vs PRE and POST vs PAD must fit the matched
ABBA null for db-0 instruction cost and rate; PAD vs PRE diagnoses code/layout/common-path cost.
Neither fewer instructions nor a favorable IPC movement excuses a rate regression. No measured
cells, null comparison, or zero-cost verdict is present in this report.
