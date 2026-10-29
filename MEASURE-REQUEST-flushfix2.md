# Atomic FLUSH publication — review and measurement request

## flushfix2

Branch `cx-flushfix2`, base `393d6ceb129d8c99dffd70959d6a19267c525fe0`.
No push. Landing requires the owner's design approval. The binaries and directed
proof are frozen; broader correctness jobs below are still in progress. The
required FLUSH+FLIP liveness proof is FAIL: the unmodified PRE and final POST
binaries both abort. This lane is not an all-green correctness result.
No performance or throughput claim is made. The first full differential attempt
found the new INFO counters before the Stats header. Commit `34a2fa295` fixes
that placement; interrupted verification is retained in
`docs/flushfix2/superseded-verification.json`. All final arms below include it.

### Implementation

FLUSHALL/FLUSHDB SYNC and ASYNC force admission at both atomic settings. Each
shard joins one TO-B unit with a whole-shard Write claim and installs a zero-key
namespace record bound to the unit's epoch. The existing commit batch publishes
one ticket; phase-two owner tasks defer until the read floor and cleanup cutoff
permit physical reclamation. The command replies after every shard collapses.
`AtomicEntry` remains 144 bytes and `AtomicPendingState` remains 1352 bytes.

The fast collapse calls the existing clear/multidb routines. The slow collapse
preserves post-flush candidates and nulls their first parked predecessor, so an
aborted later write cannot resurrect a flushed value. Snapshot capture uses the
existing resumable copy-on-write gate. WATCH reservations cover present or
expired watched keys at decision; blocked stream readers are reprobed after
collapse. The poison reference spans install through reclamation.

The cold slow-collapse implementation finds each key's first later record by a
linear chain walk. With C physical slots and P later key occurrences, its worst
case is O(CP + P²); the fast path retains today's clear complexity. This is an
explicit merit risk for a populated flush with concurrent writers. The owner
should retain the slow-collapse counter and include that population/window in
the latency and writer-wait runs; the small correctness witnesses establish
semantics, not a bound on populated-flush latency.

The range resolver is in `src/store/flush.cc`; shared ordinary resolution enters
it only when a live range exists. INFO exposes units, range reads, post versions,
script conflicts, collapses and slow collapses. POST witnesses must fire all
five window counters, using fresh bounded script cuts; an unopened window fails.

AOF adds GroupFlush fragments with one GCMT. Serverless replay checks include
missing GCMT, committed GCMT, both namespaces and legacy Flush. The lifecycle
unit also checks old cuts, own private visibility, PIN-only OCC, post-delete,
rollback to absence, namespace controls and read-local reclamation.

A wounded flush must reclaim any already installed ranges before retry. The
first DEL/MSETNX liveness test exposed orphaned ranges on that path; the cleanup
wave is now mandatory for cancelled attempts too.

### Proof receipts

The original two witness files are byte-identical copies from `fccd38b77`.
PRE raw counts are in `docs/flushfix2/pre-witnesses.json`; the deterministic
PIN-only R3 failure is in `docs/flushfix2/r3-pre.txt`. The bounded fresh-boot rerun now fails all 112 target legs from actual tears,
with no transport errors; all 14 Redis oracle legs are clean. Exact counts and
every clean rearming attempt are retained in `docs/flushfix2/pre-final-witnesses.json`.

The final POST run through the gate's job interface passes all 14 directed rows
and both lifecycle/replay units: 112 target legs and 14 Redis oracle legs, zero
tears. Every target leg fired all five window counters and the forced OCC retry
returned `[1,1]`. Minimum deltas across target legs were units=1, range_reads=5,
post_versions=3, script_conflicts=2, slow_collapses=2. Exact observations and
falsifiers are in `docs/flushfix2/post-final-witnesses.json`; the ledger is
`build/flushfix2/verification/final-v2/directed.partial`.

The final binary passes all 16 legs each of DEL/MSETNX, script, WATCH/EXEC,
BGSAVE, BGSAVE-straddle and AOF-restart storms. Seven of the eight split
FLUSH+FLIP target legs pass; databases=16 / 2s / uring / atomic=1 aborts.
The generation-validated BGSAVE rerun reloads 128 new target images per family
and checks pair equality (256 total). Redis cancels active BGSAVE children on
FLUSHALL: each family had zero new oracle images and 82 cancellations. An older
receipt counted copies of an unchanged oracle file; it is superseded, not proof
of new images. No cancelled save is counted as an image checked. The stronger
AOF restart seeds one sentinel on every shard in every configured database
(256 sentinels at databases=16, 16 at databases=1), proves all were flushed,
and compares the complete key/value set and DBSIZE in every database after
restart. All 16 target and two oracle legs pass. Image hashes and counts are
in `docs/flushfix2/persistence-final.json`.

The same FLUSH+FLIP witness aborts on the unmodified PRE binary on its first
fresh recheck. Separately linked PRE and POST diagnostic binaries, with only an
abort wrapper, both identify `ExLoopT<false>::flip_control_pass()` at
`src/core/ex_loop.h:1559`: `remask_task_inbox_quiesced()` returned false during
ExInstall. This establishes a pre-existing FLIP failure (**OTHER**); it does not
diagnose which remask predicate failed. The required liveness row remains FAIL.
The normal POST failure completed 8,156 flushes / 8,186 flips before aborting;
all failure observations, commands, binary hashes and offline-symbolized stacks
are in `docs/flushfix2/flip-failure.json`. No core or attached debugger was used.

Earlier stronger retained-MULTI+DEL/MSETNX+FLUSH+FLIP probes also timed out or
failed their nonzero-FLIP assertion; they remain recorded failures. The ordinary
FLUSH+FLIP abort is now demonstrated on both arms. FLIP production code is
unchanged by this lane. `tests/gates_test.py` passes all 73 tests.

All 80 final serverless scope comparisons meet ZERO added executed instructions:
GET/SET/INCR/MGET/MSET, atomic 0/1, batch 1/32, both modes, both namespaces.
`docs/flushfix2/counts/comparison-final.json` contains every PRE/POST count.
The established fixture counts executed instructions (including NOPs) in named
TomoKV bodies, excluding library callees and fixture glue; these are scope
counts, not whole-process instruction or cycle measurements.
Read-local-1 scopes are NOT RUN: the established production fixture explicitly
sets `cfg.read_local=0` and calls the executor batch entry, so it cannot exercise
the connection's read-local lane. Live correctness witnesses do exercise it.

With eight live EXEC-format records, the atomic-1 MGET scope adds 76 instructions
in the normal image and 17 in databases-1, in either mode. Subtracting the
ordinary-cell deltas (-4/-335) gives incremental live-path differences of
80/352. These are complete scope counts, including compiler effects, not a
claim that the new resolver entry test alone executes that many instructions.
See `docs/flushfix2/live-counts/comparison-final.json`.

The final compile-only survey covers 54 units. The exact symbol inventory is
`docs/flushfix2/identity-final/bodies.json.gz`: 18,693 of 19,723 bodies in
PRE-existing objects are identical; 1,030 differ, and the two new FLUSH objects
add 188 bodies. Of the existing command-handler bodies, 1,196/1,233 are identical;
the hot-body selection is 1,509/1,589. The old audit's complete-identity guard
therefore fails; this is explicitly retained, not called an identity pass.
All changed names and object hashes are recorded. `make all` and all production
unit targets built; all 57 final `make -q` checks returned 0 (including auxiliary
makefiles and both FLUSH units), with hashes in `production-freshness.json`.
The supplemental `notifycompat` gate job passes all seven scored compatibility
rows, including FLUSH per-key event/AOF compatibility, on the final binary.
All 35 supplemental topology jobs also pass. Both fused differential engines
pass 466 rows each, with standard seeds; their ten SORT skips per engine are
listed below. Broad correctness and split differential runs remain in progress.
The original T9 broad row failed because the blind-restart window did not open;
a bounded fresh-server recheck of the unchanged complete T9 job passes all 27
legs, with its restart counters nonzero. The original failure is retained in the
broad ledger and `docs/flushfix2/t9-rechecks.json`; no tolerance was changed.

### Sibling sweep

Raw observations, errors, commands and exit receipts are retained in
`docs/flushfix2/sibling-receipts.json`. Final POST siblings and loaders use
`final-v2`; PRE loader evidence uses `pre-loaders-corrected`. Earlier corrected
POST loader results remain in `post-loaders-corrected` as superseded evidence. Earlier loader attempts were inconclusive: TomoKV
rejects Redis's optional `DEBUG RELOAD NOSAVE` grammar, and the first harness
mistook Redis's expected LOADING replies for a failure. The corrected witness
uses common grammar, records LOADING separately, and runs atomic script
increments beside both loaders. It asserts equal pairs and monotonically
increasing single-key GET values.

| Sibling | Classification and evidence |
|---|---|
| FLUSHALL ASYNC; FLUSHDB SYNC/ASYNC, both images | SAME DEFECT on PRE, fixed on POST; included in all-leg directed proof |
| SWAPDB | CLEAN in both images; db1 exercises `SWAPDB 0 0`; nonzero swaps and observations |
| MOVE | OTHER at atomic 0: cross-DB gap or duplicate on PRE/POST, the documented mover relaxation; atomic 1 CLEAN; db1 same-DB refusal matches oracle |
| COPY ... DB; RESTORE REPLACE | CLEAN in directed replacement/observer checks and oracle semantics |
| SCRIPT/FUNCTION FLUSH SYNC/ASYNC | CLEAN: no keyspace effect |
| WATCH present/absent | CLEAN: present-key watch aborts; absent-key watch remains valid |
| CLIENT TRACKING null invalidation | OTHER on PRE/POST: OK precedes null invalidation; Redis sends invalidation before OK |
| Blocked XREADGROUP; own pipelined FLUSH/GET/SET/GET | CLEAN; replies match oracle. Armed fused pipeline GETs take in-flight-write fallbacks; subsequent clean GETs fire read-local hits |
| BGSAVE straddle; AOF restart | CLEAN in the final bounded rows described above |
| DEBUG RELOAD/LOADAOF | SAME DEFECT: mixed pairs and backwards single-key GETs on PRE/POST; corrected oracle rows all clean. Some LOADAOF legs also return load errors or stall (OTHER) |

Loader totals (all eight legs attempted per cell):

| Loader / databases | PRE torn pairs / backwards GETs | POST torn pairs / backwards GETs |
|---|---:|---:|
| RELOAD / 16 | 114627 / 361 | 237971 / 1276 |
| RELOAD / 1 | 44620 / 235 | 252694 / 1316 |
| LOADAOF / 16 | 64418 / 716 | 89166 / 2867 |
| LOADAOF / 1 | 70439 / 1081 | 78150 / 2095 |

The LOADAOF totals include only actual observations: PRE databases=16 /
1s-uring-0 and final POST databases=1 / 1s-uring-0 and 1s-uring-1 stall before a
successful load and are not atomicity passes or tears. Other legs demonstrate
the pair/single-key defect with successful loads and no transport errors.
No nil single-key GET was observed in these corrected runs; backwards values
are the demonstrated single-key failure. Production loaders are unchanged.
Their repair needs the SWAPDB database-boundary route: drain IO and executors,
retain one boundary across clear/load, and reopen after every owner completes.
That boundary must also exist in the single-database image, where SWAPDB's
current boundary is compiled out. Range records alone do not make a loader's
replacement dataset one publication.

`tests/gate.sh` currently adds 14 directed rows and two serverless rows at
the `collect_job flushfix2` / `collect_job flushfix2_units` lines **5822/5823**,
before the quick-tier exit at **6116**: DQ=+16, DF=+16. With base constants 881/898, the owner would
set 897/914. EXPECT_QUICK and EXPECT_FULL are unchanged.

### Owner's merit run

Use the gate's instrument on a quiet box, with PRE, POST and PAD-A. PAD-A means
**(A) behaviour twin**: PRE FLUSH routing/behaviour in the candidate's exact ELF
text size, function addresses and section layout. Four three-byte patches disable
the cold FLUSH routing predicate and snapshot continuation pump in both images;
all other candidate bytes remain unchanged. Candidate budgets and dormant
range-aware code remain. SHA-256s, offsets and exact section/symbol checks are in
`docs/flushfix2/pad-a.json`. PAD-A tears on all 16 flush-only legs across the two
images (`docs/flushfix2/pad-a-witnesses.json`). PAD-B is not requested.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/flushfix2/pre/tomokv` | `e1f756b465273991a42b350986645a2660700bee6d71404b9630182789528d3e` |
| POST | `build/flushfix2/post-v2/tomokv` | `7389c241a63ed94d17a03c447c90bba6ae1dde422f0fe6a9edb728006d13bad8` |
| PAD-A | `build/flushfix2/pad-a-v2/tomokv` | `2f7c9591acc21effb52787cc75194f9d6f9426e63e36538027c7f264d0b0832e` |

POST's production source is commit `34a2fa295`; later commits add tests/receipts.
`.text` is 8,551,031 bytes on PRE and 8,653,079 on POST/PAD-A (+102,048).
`make -q all` returned 0 after the final build. Exact artifact sizes and hashes
are also in `docs/flushfix2/delivery-arms.json`.

Measure:

- The 14 generic cells, with the gate's usual ABBA repetitions and matched load.
  Their exact definitions plus the four split null cells are frozen in
  `docs/flushfix2/merit.cells.txt` (source hashes in `merit-cells.json`).
- Split GET/SET at pipeline 1 and 32 as the null cells (`h53/h54/h21/h22`).
- Atomic-1 MGET: eight fixed keys spread across the 16 shards, 64-byte values,
  64 reader connections at pipeline 8; eight writer connections repeatedly run
  `MULTI; SET` for the same eight keys followed by `EXEC`, one transaction in
  flight per writer. Run both modes and both database images, read-local 0.
  Establish an offered load sustainable by all three arms, then hold that load
  and the writer schedule fixed across ABBA blocks. Require sampled live
  `atomic_entries` and a nonzero `atomic_predecessor_reads` delta. Retain
  cycles/op, IPC and instructions/op separately; report reader and writer rates.
- FLUSHALL SYNC and ASYNC: 0, 1M and 10M keys, 16-byte keys and 64-byte values,
  uniformly spread over all shards in DB 0, no TTLs. Test both modes/images at
  atomic 0/1; read-local 1 for fused and 0 for split. Freshly reseed outside each
  timed interval, include empty-keyspace trials, and record at least 100 flushes
  per nonempty cell (1000 empty). Report p50/p95/p99/max command completion
  latency and memory reclamation, retaining the individual observations. Use the
  same population and repetition schedule for PRE/POST/PAD-A.
- Writer wait: repeat FLUSHALL SYNC/ASYNC at a fixed 10 Hz with 16 SET writers,
  pipeline 1, distributed across all shards; run separate same-key and disjoint-
  key schedules and a no-flush control. Keep offered load below the slowest
  arm's capacity. Report p50/p95/p99/p99.9/max for client completion latency and,
  with owner-side timing enabled identically in all arms, claim wait from first
  placement defer until successful placement. Record the wait count and
  distribution separately from flush decision-to-collapse time. Client RTT
  alone is an upper bound and must not be labelled pure claim wait. The
  production counters count waits; they do not supply a duration histogram.

Rate at matched offered load decides regressions in ordinary cells. The latency
and writer-wait distributions judge the additional publication/floor-drain cost;
instruction counts alone do not establish a gain. Correctness and the zero-tax
scope requirement must pass before any merit conclusion.

All lane builds and correctness work use CPUs 0–15 (builds `-j16`), 16-shard
gate geometry and split ratio 6:2, and ports 20100–20199. Main servers use CPUs
0–7; the supplemental topology and fused differential runs use CPUs 8–15, with
load CPUs exchanged, so both stay within the lane allocation.
Every boot inherits LC_ALL=C. No full iteration or performance benchmark is run
by this lane. No debugger attaches to servers and no core-dump tool is used.

### Deliberately unrun work

- Performance cells, latency merit runs, writer-wait timing and the full
  `tests/gate.sh iteration`: NOT RUN; reserved for the maintainer by this task.
- Serverless read-local-1 instruction cells: NOT RUN; the existing fixture
  explicitly disables that connection-side lane. Live read-local correctness
  and the fused differential suites cover its behavior separately.
- Fused SORT differential legs: NOT RUN; that generator requires the split
  6:2 geometry and the standard harness explicitly skips it for fused boots.
  The split differential suites run it.
- Reloading oracle images from the generation-validated FLUSHALL/BGSAVE storm:
  NOT RUN; Redis cancelled those children and published no new images. The
  cancellation outcomes were checked and no old file copy is credited as a
  completed storm snapshot. POST's newly published images were all reloaded.
