## savefix

Worktree `/home/user/Projects/cx-savefix`, branch `cx-savefix`; no push. PRE is
`5146b78ee89b64748dd46db970efa8086f653fa0`. `origin/cpp` was fetched again before
final focused proof and still pointed there; no merge was needed.

The final 24 live regressions fail for the intended defect on PRE and pass on
POST. Their complete paired results and timings are in
[rows.md](docs/savefix/proof/rows.md), with unchanged assertion code for both
arms and raw [PRE](docs/savefix/proof/pre/results.json) /
[POST](docs/savefix/proof/post/results.json) receipts. The longest row took
30.601 seconds. There is a separate, reproduced baseline AOF shutdown hang with
undecided EXEC work; this branch does not claim to fix it. See the owner
decisions below before landing.

**PS4.10 — acknowledged writes absent from the final dump.** At this baseline,
`Server::shutdown` already requests a blocking capture. The admission hole is
on the final-chunk pass: Capturing became Draining, letting that pass admit
Ready writes before the next control pass installed ShutdownHeld. The owner
now enters ShutdownHeld and counts `owner_finished` on that same final-chunk
pass. The final cut also gates parked blocking operations and self-directed
stale forwards that can mutate outside the ordinary inbox drain. Failure still
releases the hold and resumes service. The post-cut reply gap is covered by a
serverless assertion which fails on PRE.

All eight PS4.10 rows (1s/2s × SIGTERM/SHUTDOWN × uring/epoll) lose one or more
of the eight writers' last acknowledged values on PRE; POST loses none.
Additional atomic-MSET final saves and SIGTERM during an older BGSAVE with
save configured fail on PRE and pass on POST in both thread modes. Both
AOF-enabled final-save controls pass on POST. The Redis 7.4.10 SIGTERM oracle
retains all eight acknowledged values.

Production files: `src/core/ex_loop.h` (admission and final-chunk transition),
`src/cmd/server_tail.cc` (corrected cut comment). `src/core/server.h`, including
the signal request path, is unchanged. No signal-handler or FLIP change.

**PS4.11 / AT26 — active capture prevents post-join atomic collapse.** The
physical snapshot writer marks cancellation and reaps its own submitted
snapshot IO before it exits. This must run on that thread because its ring
uses SINGLE_ISSUER/DEFER_TASKRUN; trying to reap from main after joining hung
an initial candidate, whose failed output is retained. The snapshot lifetime
guard follows the AOF drain in destruction order. After all workers join,
`cancel_after_join` discards capture chunks, closes/unlinks the temp file,
ends rewrite state through the existing `rewrite_abort`, cancels every store
capture, and only then permits `atomic_shutdown_release_records`.

All sixteen cancellation rows (BGSAVE/rewrite × 1s/2s × atomic 0/1 ×
uring/epoll) observe a live capture, real incomplete file prefix and live MVCC
records. PRE aborts with SIGABRT, omits its shutdown report and leaves the temp
file. POST exits 0, removes the temp file, produces the normal report and
replays every acknowledged group for the AOF case. All 72 final report checks
(`present`, `io`, `persistence` on each row) pass. [Report receipts](docs/savefix/proof/shutdown-report-checks.json).

Production files: `src/snapshot/snapshot.{h,cc}`, `src/main.cc`,
`src/core/genthread.cc`, `src/core/rl2s.cc`. The two additional entry files are
necessary to apply the same joined cleanup and physical-worker lifetime to
fused and split read-local boots. No wider shutdown design was introduced.
The abort guards in `flatstore_atomic.inc` are unchanged. `aof.cc`, including
`rewrite_mark`/`rewrite_abort`, and the separately owned snapshot chunk-channel
wake are unchanged. Snapshot bytes and format are unchanged.

**Regression arming and scope.** `tests/savefix.py` owns fresh directories,
its exact child PID, both boots, and its port. It accepts `--binary`, `--port`,
`--cores`, mode, atomic setting and engine. Defaults are 131,072 keys × 200
bytes for the snapshot rows and 524,288 × 200 for rewrite. Population uses
bounded MSET frames. Eight writers each have one request outstanding; atomic
0 cancellation uses MULTI/EXEC, atomic 1 uses MSET. Acknowledged-write rows
keep writers active throughout shutdown.

Cancellation rows finish outstanding requests and then **re-observe** live
MVCC entries, the in-progress flag and a real prefix smaller than half the
dataset before signalling. The rewrite dataset is larger to leave that window
open through AOF acknowledgement. Three fresh datasets are the fixed arming
bound; a missing window fails. No tolerance is widened and no case skips.
The paused rows additionally assert the full persistence-report drain.
`--writers-inflight 1 --keys 131072` preserves the original independent
unfinished-group stress. Its intermittent PRE and POST hangs remain evidence,
not passing controls. Historical attempts, supplemental controls and failed
initial candidates are preserved byte-for-byte in
[history.tar.gz](docs/savefix/history.tar.gz), with a
[per-file SHA-256 index](docs/savefix/history-index.json). Earlier smaller paused rewrite attempts that missed the
window also remain failures in the historical receipts.

**Gate accounting, counted by line.** The three new row sites are
`tests/gate.sh:2312` (acknowledged writes), `:2323` (BGSAVE cancellation), and
`:2608` (rewrite cancellation). They are emitted in `job_snapshot` / `job_aof`,
whose collections precede the quick-tier exit at `:3456`. Each site emits
2 × 2 × 2 = 8 rows. DQ = **+24**, DF = **+24**. The existing shutdown-unit row
is extended, not counted again. No row is added to `core_units`.

The job-owned listener is stopped before these self-booting rows take `$PORT`;
AOF's following boot takes it back afterward. All 24 labels are in
`tests/fixtures/nullrefresh-ledger-labels.json`. Required owner updates:
**EXPECT_QUICK = 511 + 24 = 535; EXPECT_FULL = 528 + 24 = 552**. The arithmetic
comment is immediately above the untouched constants.

The raw ledger fixture check refuses the intentionally unchanged 528 count:
fixture/source labels agree (552, missing/extra none), but fixture length is
not EXPECT_FULL. It cannot pass until the maintainer performs the forbidden-to-
lane count edit. The checker itself is unchanged. An in-memory prospective
552 check validates the planned labels; it is explicitly not a raw checker
pass. [Raw refusal](docs/savefix/ledger.log), [prospective inventory](docs/savefix/planned-ledger.json).

**Build and focused proof.** Every process was constrained by
`taskset -c 112-127`; target listeners use 112–119, oracle 120 and differential
clients 121–127. Ports used stay within 25014–25027. Every race log records
load average and per-CPU ticks; final PRE rows saw one-minute load
103.35–144.61, POST 108.61–144.80. These were contended correctness runs, not
performance measurements.

- PRE `make -j16 BUILD_ROOT=build/savefix/pre all` and POST `make -j16 all` passed.
- All 28 production-unit targets, including shutdown-unit and persistfix-units,
  built successfully with `make -k -j16`; build time 1304.758 seconds. Both
  `mdbqsbr-live-arms` binaries built (876.943 seconds, including the documented
  compiler pause). All **28/28 `make -q` freshness checks pass**.
  [Compressed build logs](docs/savefix/build/receipts.json); complete target receipt: [production-units.json](docs/savefix/production-units.json).
- Differential: **64/64 suite/seed/atomic/geometry legs, zero differences**,
  plus both armed-fused read-local witnesses. Suites `psfix multi xshard
  servertail`, seeds `7 19 20 23`, atomic `0 1`, split 6:2/16 shards and armed
  fused. [Commands and environment](docs/savefix/differ.json),
  [split](docs/savefix/differ-split.log), [fused](docs/savefix/differ-armed-fused.log).
- `shutdown_persist.py --case all` and `persistfix.py --case term` passed in
  1s and 2s. `shutsave.py`: SAVE/BGSAVE × sigterm/nosave/shutdown × 1s/2s,
  all 12 passed, with 16,384 × 4096-byte values and the real-prefix assertion
  intact. [Auxiliary proof](docs/savefix/auxiliary/results.json).
- AT15: both namespaces × both thread modes passed. EXECABORT/WATCH: both
  namespaces × both thread modes × armed/no-watch/no-error passed; both
  no-arm controls failed with `WATCH window never armed`, as required.
  [Unit receipts](docs/savefix/units/results.json).
- `shutdown-unit` passes, including the new immediate owner-hold assertion and
  live-record capture cancellation. The simulated timeout retry now keeps the
  same virtual clock as its first attempt, retaining the 4,096-pass progress
  bound; shared-box wall time had otherwise expired while scanning old tables.
  Both the unchanged PRE unit and a diagnostic unoptimized fixture passed; the
  failed optimized attempts and final passing log are retained.
- `python3 tests/gates_test.py` is **not green**: 66 tests ran, with 13
  scheduler-fixture failure records in the final build-paused run; nested
  identity controls passed 14/14. Earlier runs recorded 12 and 13 failures.
  These are the unchanged 45s fixture deadline (exit 124), under continuing
  shared-box contention; no timeout or assertion was changed. A quiet-box
  owner rerun remains required. [Final log](docs/savefix/gates-test-build-paused.log),
  [pause/resume receipt](docs/savefix/gates-test-build-paused.json). The
  collector, placement and ledger inputs match PRE; the scheduler slice differs
  only in the two production job bodies replaced by the fixture stub.
  [Input comparison](docs/savefix/proof/scheduler-inputs.json).
- `bash -n tests/gate.sh` and source/test whitespace checks passed.

**Default-build identity**, using the unmodified ttlclean/deadswitch tools.
Identical bodies compare instruction bytes with relocation targets resolved;
the lbstall selection has 1,158 raw-byte matches and 1,167 canonical matches:

| Check | PRE | POST | Result |
|---|---:|---:|---|
| Production objects | 100 | 100 | Same inventory, both namespaces |
| Full bodies, tomo | 8,391 | 8,396 | 8,331 identical, 66 changed/added/removed |
| Full bodies, tomo_db0 | 7,902 | 7,910 | 7,840 identical, 70 changed/added/removed |
| Hot bodies (lbstall), tomo | 601 | 601 | 582 identical, 19 changed |
| Hot bodies (lbstall), tomo_db0 | 603 | 603 | 585 identical, 18 changed |
| Command handler bodies | 1,210 | 1,210 | All identical, including relocations |
| Full audit hot selection | 1,208 | 1,208 | 1,167 identical, 41 changed |
| `.text` bytes | 7,582,188 | 7,585,260 | +3,072; linked image differs |
| Locked sizes and all checked field offsets | baseline | unchanged | Both namespaces match |

The 41 changed hot bodies are listed individually with their reason in
[hot-bodies.md](docs/savefix/identity/hot-bodies.md). Owner-loop admission changes
are intentional. Unedited dispatch/writeback/FlatStore bodies also drifted
because the added code changed GCC inlining within existing translation-unit
budgets; flags and budgets are unchanged. The strict equality tools return
nonzero for these real differences. This is not a claim of instruction or
performance neutrality. [Full summary](docs/savefix/identity/full/summary.json),
[full inventory](docs/savefix/identity/full/bodies.json.gz),
[hot audit](docs/savefix/identity/hot.json),
[linked sections](docs/savefix/identity/linked.json),
[layouts](docs/savefix/identity/layouts.json).

Locks remain Op 336 / Client 1984 / ThreadCtx 1408 / Shard 1440 / FlatStore 944 /
Rob<64> 192 / AtomicEntry 144 / Config 624. No data-layout PAD arm is required
or named. There is no format, read retry, seqlock, owner-migration or mutable
read-local-record change.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/savefix/pre/tomokv` | `67d5cdd5432f8517c031ac35a1ff525dffcbf6d391ef2fcce35e4bfdf20dd900` |
| POST | `build/tomokv` | `520d03703f5b0719cc92223b66073777d9c9c863efa8e44f88a9312c58fdd1be` |
| Redis 7.4.10 | `/tmp/claude-1000/redis74/src/redis-server` | `ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b` |

**Owner decisions / limits.** Continuous in-flight EXEC with AOF can hang in
shutdown on PRE even with **no snapshot ever started**. The initial POST
capture stress also observed AOF `drain_gave_up`/pending producers. The new
capture cleanup runs after that lifecycle, so it cannot repair this older AOF
rendezvous. A bounded independent reproduction is
`docs/savefix/no_capture_control.py --binary build/savefix/pre/tomokv --port
25014 --cores 112-119 --output build/savefix/new-no-capture`, invoked beneath
`taskset -c 112-127`. The retained no-capture PRE failure and original in-flight
PRE/POST failures require a separate AOF owner decision; this lane preserves
the safe snapshot fix without changing aof.cc.

An extra (unrequired) databases=16/read-local=1/atomic=1 probe also lost its
connection during the initial large MSET population on PRE and POST, before
any capture or shutdown. It is not counted as a savefix failure or proof.
Read-local atomic-0 acknowledged-write/BGSAVE checks pass in both modes,
and the scoped fused rewrite check also passes. These and the required
differential matrix provide the completed evidence; the population failure is retained for the
owner. GDB attach was unavailable in this environment, so no stopped-thread
trace is claimed for either independent issue.

SHUTDOWN FORCE/NOW parsing remains unchanged: those flags are still ignored.
Because they alias the same shutdown path, a successful final save also gains
the corrected acknowledged-write cut. This is not a PS4.12 implementation.
SIGKILL cannot run the new guards/cleanup; PS11 orphan-temp behavior is unchanged.

**Measurement request.** No benchmark or complete gate was run. The owner must
run the mainline performance null with these PRE/POST binaries on the quiet
box after integration. Use all 181 cells in `tests/headline_cells.txt` (`--subset full`),
with A=PRE and B=POST in A/B/B/A order; retain per-cell cycles/op, instructions/op and IPC
and matched-offered-load rates. The verdict is the gate's observed-spread null,
not instruction count alone. Record results here as MEASURE-RESULT; no runtime
performance result is asserted by this branch.
