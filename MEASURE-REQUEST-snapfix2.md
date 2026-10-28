# Snapshot table sizing and FLUSHALL isolation

## snapfix2

Worktree `/home/user/Projects/cx-snapfix2`, branch `cx-snapfix2`, PRE `a214652ec`,
BASE `5572e84cc`. All builds and correctness processes use CPUs 0–15; servers use
0–7 (16 shards, split ratio 6:2), drivers 8–15, ports 20100–20199. No push and no
performance measurement in this lane.

### Sizing review

The proposed `docs/snapfix/followup/table-sizing.patch` needs a correction.
`snapshot_prepare` runs before owners freeze. Both `insert` variants and both
`atomic_prepare_capacity` variants admit new keys up to the **current** capacity
while prepared. Sizing a sparse 1024-slot table's destination to 128 can therefore
accept 513 keys before Mark, then leave a destination too small for the merge.
The directed addition to `storage flush-prepared-capacity regression` exercises
that schedule with read-local both armed and disarmed and fails before a stuck
merge on the unfloored proposal.

POST chooses `max(old_capacity, 2 * min(live_capacity, old_capacity))`, where
`live_capacity` is the smallest power of two from `kMinCap=64` for which
`(live+1)*100 < capacity*kLoadPct` (`kLoadPct=70`). Tombstones are omitted from the
fresh destination's sizing because the merge drops them. The current-capacity
floor preserves every prepared insert/reservation's existing bound; the upper
bound is the old allocation rule. The post-cut gate still reserves space for all
current live keys, current tombstones and frozen live keys. No command admission,
read visibility, object layout, QSBR or retirement rule changes. Existing oversized
tables are retained until ordinary deletion-driven shrinking; future idle saves
do not compound them.

The sole production caller is `ExLoopT::snapshot_control_pass` in Preparing.
SAVE, BGSAVE, save-rule cron, shutdown-save, enabled-AOF rewrite and offline-AOF
rewrite all use `SnapshotManager::start` and that owner path. Read-local Mark uses
the same prepared allocation. Completion/cancellation leave it for the ordinary
bounded merge. FLIP creates no snapshot table; its transition mutex and snapshot
admission exclude simultaneous placement changes, and the shared atomic barrier
drains units before the snapshot cut.

### Directed rows

`snapfix2_tables` independently runs 12 idle BGSAVEs on 1s/2s × uring/epoll ×
atomic 0/1 and Redis 7.4. It is collected immediately after `snapfix_bgsave_exec`,
before the quick-tier exit: **DQ=+1, DF=+1 relative to BASE**. EXPECT constants are
unchanged. Including snapfix's inherited +3/+3, the maintainer's 807/824 becomes
811/828. PRE fails the RSS bound on all eight TomoKV legs; Redis passes.
Receipt: `docs/snapfix2/proof/rows-pre/record.json`.

The prepared-capacity addition remains inside the existing storage regression;
there is no second new row. Removing the capacity floor from POST makes it fail
with `prepared destination holds accepted keys`, exit 1, before any unbounded
merge (`docs/snapfix2/unit/unfloored.json` and `unfloored.patch`). The test prepares
a sparse 1024-slot store, admits another 512 keys before Mark, then requires the
capture and merge to complete with every accepted key, with read-local off/on.

### Compiler budgets and body identity

The corrected formula adds **19**, not the unfloored proposal's 14, IPA
instructions in each of the eight IO units. Compile-only trial receipts are in
`docs/snapfix2/budgets/`; the selected receipt lists each command and object hash.
The selection rule minimizes changed hot bodies, then changed bodies of any
kind, then distance from BASE + 19. Units that already changed only snapshot
control retain their old budget.

| Unit | BASE budget | POST budget | BASE → POST initial IPA size |
|---|---:|---:|---:|
| src/main | 147838 | 147838 | 102431 → 102450 |
| db0/main | 146080 | 146080 | 101687 → 101706 |
| src/genthread | 131241 | 131253 | 109386 → 109405 |
| db0/genthread | 132035 | 132058 | 108600 → 108619 |
| src/rl2s | 164644 | 164662 | 118250 → 118269 |
| db0/rl2s | 167496 | 167496 | 117327 → 117346 |
| src/reorder | 149134 | 149153 | 122002 → 122021 |
| db0/reorder | 150113 | 150133 | 121085 → 121104 |

The complete 118-object comparison against BASE has 17,945 function bodies across object files: 17,929
identical, 15 changed, one added function and no removed or padding-only bodies.
Eight changed bodies are the intended `snapshot_control_pass` instantiations.
The added body is db0 `service_snapshot_backlogs<false>`, now out of line.
The remaining seven are `kvobj_external_bytes` ×2, db0 `rehash_step_read_local`,
db0 `atomic_prepare_capacity_read_local`, `maybe_start_shrink`,
`pubsub_deliver_one`, and one fused `flush_ready` specialization. The exact
per-symbol lists, rather than this prose, are authoritative:
`docs/snapfix2/identity/base-post.json` and `pre-post.json`.

**Residual hot change:** the normal fused
`flush_ready<false,true,true,false,true,false>` is not body-identical at any of
this lane's tested budgets. It is not part of the command execution fixture.
Neither the body comparison nor equal command counts proves a throughput null;
the release and PAD-A merit comparisons remain required. No rate claim here.

Serverless GET/SET/INCR/MGET and MSET (atomic 0/1), batch 1/32, both modes and
both namespaces were counted on PRE, BASE and POST by
`tools/snapfix2_artifacts.py scope`. This launches GDB only on the serverless
fixture; it never attaches to or debugs a server. All **48 cells per arm**, hence
**96 PRE/BASE-vs-POST comparisons**, have identical totals and per-function
counts: zero added executed instructions in the named production routines and
inlined code. As in snapfix, the fixture excludes library callees and fixture
glue, runs with no snapshot armed and read-local 0, and uses atomic 1 except the
additional MSET atomic-0 cells. Totals are recorded in
`docs/snapfix2/instructions/comparison.json`.

### FLUSHALL: pre-existing atomicity defect, separate repair required

The existing PRE receipts already show torn pairs without BGSAVE; removing both
BGSAVE and FLUSHALL made all eight TomoKV legs and Redis clean. The independent
`tests/snapfix2_flush.py --case flush-pair` reproduces on PRE's 1s/uring atomic
0/1 with one serial EXEC/FLUSHALL connection and one MGET observer. Each completed
Redis command leaves either `[1,1]` or `[nil,nil]`; a mixed pair is invalid.

Root cause in unchanged production code:

- `scatter_engine.inc` lowers FLUSHALL/FLUSHDB to `Kind::AllShards`, which is
  excluded from `is_atomic_write_kind`; the all-shards dispatch barrier is not
  a shared atomic visibility publication.
- Each shard's AllShards handler calls `Shard::watch_flush`, then `cmd_flush`.
  `watch_flush` invokes `FlatStore::atomic_tombstone_all`, which obtains its own
  `atomic_ticket_fn_` ticket and installs plain, already-decided tombstones.
  Thus different owners publish different flush cuts. Untracked keys are then
  physically cleared by `clear`/`clear_during_snapshot`.
- A reader cut can fall between those owner-local publications, and a writer
  unit can encounter different clear ordering at its different owners. The
  shard-local foreign-read poison covers one owner's mutation; it supplies no
  single commit point for the entire FLUSHALL.

A single shared ticket alone would still leave untracked keys without preserved
preimages and must coordinate publication with all owners and concurrent units.
A local change to snapshot sizing cannot establish that protocol. No reader
retry, seqlock, reader-blocking lock, or weakened EXEC/script guarantee is added.
This defect is handed off with exact PRE/BASE/POST isolation receipts; it is not
silently accepted as a passing gate row.

The stronger `--case flush-only` rearms two keys with acknowledged SETs while its
observer is parked, requires an observer read before issuing FLUSHALL, and parks
the observer again before rearming. The only concurrent mutation in that window
is FLUSHALL: no EXEC, scripts, BGSAVE or unrelated writer. Every attempt uses
fresh logical state, and missing observations/worker progress fail.

Minimal reproduction (use `flush-only` to isolate the clear itself):

```sh
taskset -c 8-15 python3 tests/snapfix2_flush.py --case flush-pair \
  --binary build/snapfix2/pre/tomokv \
  --oracle /home/user/Projects/redis/src/redis-server \
  --cores 0-7 --port 20100 --modes 1s --engines uring --atomics 0 1 \
  --seconds 5 --output build/snapfix2/reproduce-flush
```

### Correctness proof

`tools/snapfix2_verify.py` records command lines, binary/oracle SHA-256, exit codes
and logs, and drives the gate's **partial job interface**. No full iteration,
ABBA or NIC pass runs. `GATE_PROOF_NO_RATES=1` suppresses only the existing
atomic RYOW performance assertion. The first main pass was interrupted before
that job to enable the switch; its 18 completed rows and interrupted shutdown
row are retained in `proof/proof-uring-interrupted` and are not the final proof.
The oracle is Redis 7.4.10, verified with `--version`; command receipts bind its
binary digest. The main targeted pass completed: **53 jobs, 329 ok, 0 FAIL**, including all
snapfix rows and the new RSS row (`proof/proof-uring/record.json`). The idle RSS
row passed all eight TomoKV legs plus Redis: 1s stayed at 18.79–18.87 MiB and 2s
at 15.30–15.38 MiB over 12 saves. Both storm rows passed all nine legs.
The FLUSHALL matrix, larger/longer RSS checks, other engine pass and differential
suites remain in progress. Initial
`tests/gates_test.py` hit three fixture timeout failures while compilation and
instruction tracing overlapped; it will be repeated in isolation, with the
original log retained. No assertion or timeout is weakened.

### Arms

PRE and BASE sources were compared file-by-file with their Git objects: 1,059
PRE files and 1,073 BASE files match, with zero mismatches. Both builds pass
`make -q all`. See `docs/snapfix2/reference-builds.json`. Debug paths make their
binary digests differ from the other worktree's builds.

PAD is **A (behaviour twin)** relative to BASE: BASE behaviour in the exact common
POST-layout image. `POST-layout` and `PAD-A` have identical sections, symbols and
function addresses; only the five-byte entry branch differs. They are larger
than the release binary, so compare those twins separately. The generator and
all object/input digests are recorded in `docs/snapfix2/pad-a.json`.


| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/snapfix2/pre/tomokv` | `da219bf6c15d7f7649e6f6f2758ed7407f8ba6e4456ef48ea2a416ba01de710c` |
| BASE | `build/snapfix2/base/tomokv` | `dea9309b1ebdf5a46da5fc69d377ed55b26414e7e01d38d3ddfa4b2a8b61db98` |
| POST | `build/tomokv` | `dd169c2f10040c4b13cb87c3731e4ba1a2dbd74088635008e8512ba64e84021c` |
| POST-layout | `build/snapfix2/POST-layout` | `e091b35599b3c8ec893facb4132a5d3996fb35a076557303c11174f26df67346` |
| PAD-A | `build/snapfix2/PAD-A` | `a5f898e5e659944c8f328280654328df4dad60c53fcbf0e6213ce14937303a34` |

Section sizes and merit-cell digests: `docs/snapfix2/arms.json`. POST release
`.text` is 8,459,175 bytes, **+160 bytes** versus BASE.

### Maintainer measurement request

Use the gate's own ABBA instrument for the 14 generic cells in
`docs/execfair/cells/generic14.txt` and 2s GET/SET p1/p32 (`tests/headline_cells.txt`
h17, h18, h49, h50). BASE vs POST is the sizing-fix comparison; retain PRE vs POST
for the combined snapfix change. PAD is **A, behaviour twin**: BASE behaviour in
the exact POST-layout common image. Compare POST-layout vs PAD-A separately from
the release binaries. Command counts are equal; matched offered
load, cycles/op and IPC decide any performance effect. No throughput claim here.

On a quiet box, also record RSS and BGSAVE start latency for each of 16 consecutive
saves, BASE vs POST, idle one-key geometry, both modes/engines, atomic 1. Use 16
shards, CPUs 0–7, ratio 6:2 in 2s; read-local 1 in 1s and 0 in 2s; databases 16;
key/client balancing and automatic FLIP off; save rules disabled. Start latency
is command send to BGSAVE acceptance reply; sample INFO memory RSS after each
completed save. Plot all 16 save indices. The capacity/RSS growth and start-wait
curves decide this stability effect. Correctness RSS checks in this lane do not
establish a latency or throughput result.
