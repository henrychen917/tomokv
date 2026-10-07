# ccfix5 — armed differential diagnosis

Both causes are identified and fixed. A is a resettable-counter witness bug;
B is a pre-existing DEBUG geometry bug after SWAPDB. Neither is a read-local
eligibility regression in the CC11 classifier. All ccfix legs and read-local
witnesses pass across three armed executions. Two complete armed matrices pass;
the other found a separate GEO fixture race, retained as a failed run and then
corrected with bounded fresh-state rearming. Split and all five instruction
witnesses pass. This is not a full landing-gate or performance receipt.

## Frozen source and binaries

Started at ccfix4 `99545f868`; merged local `origin/cpp`
`dbd01dd99269d10225f7f3d17d300cb3f653b654` in `1ebeceac0` before building.
PRE is a fresh archive/build of that upstream commit. POST is the merged
ccfix source plus the cold DEBUG namespace correction, production commit
`4b825cf5a405645b82a1f7f794d8c5bfb3321f91`. No compiler budget, layout or runtime
knob was changed. Both builds use the repository Makefile and GCC 13.3.0 on
CPUs 112–127, initially eight jobs per arm; the DEBUG change rebuilt the two
t_server objects with two jobs. Tests and production sources are frozen during
the final matrices.

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/ccfix5/PRE/tomokv` | `7a309dc43071aab9cfe59155515b268dd2cf08b089105cd8a5007224d142e92b` |
| POST | `build/ccfix5/POST/tomokv` | `67b3ef185bcd62596d993b9c293ebfc84749b565d47a4d2f2e8647272b952f22` |
| Review | `build/tomokv` | `67b3ef185bcd62596d993b9c293ebfc84749b565d47a4d2f2e8647272b952f22` |

[Checksums](docs/ccfix5/SHA256SUMS), [production blobs](docs/ccfix5/source-manifest.json),
[merged PRE→POST patch](docs/ccfix5/production.diff), and
[ccfix5 production delta](docs/ccfix5/ccfix5-production.diff) are retained.
The [build manifest](docs/ccfix5/build-manifest.json) records every object hash.
The original landing executable is preserved as `build/ccfix5/landing-tomokv`;
the merged POST before the DEBUG correction is
`build/ccfix5/merged-before-debug-fix-tomokv`, SHA-256
`96f949e0dcc4264e094cdff010f4099f2cc033c6c31ea8a3787803b79033ae1c`.
There is no PAD arm: no layout change or optimization is proposed. This lane
adds 48 bytes to cold DEBUG .text; PRE→final POST .text is +560 bytes including
the inherited +512. No throughput benchmark or push is performed. The explicit
ccfix5 task authorizes these correctness runs on 112–127.

## A: RESETSTAT erased the witness

The original row sampled INFO only once, after all suites. That value is not a
lifetime count. `command_config_resetstat()` snapshots `ReadLocalStats` through
`collect_stat_totals()`, and `cmd_info()` subtracts `baseline.read_local.hits`
(and the other read-local counters): `src/cmd/t_server.cc:1727,1981,3099`.
CC18 explicitly exercises RESETSTAT three
times, including at the end of its suite. The following psfix suite performs
configuration/persistence operations and contributes no ordinary GET hits in
atomic=0. Atomic=1 then runs four seed-19 MULTI repeats, which leave a small
post-reset count (21 after the last repeat in final run 1). That explains
why its original terminal witness still passed. The terminal zero in atomic=0
says nothing about earlier lane execution.

The full replay on POST, eight fused threads on 112–119, load on 120–127,
16 shards, `--read-local 1 --atomic 0 --databases 16`, gives seed 7:

| Observation | hits | fallbacks | arms | effective read_local |
|---|---:|---:|---:|---:|
| ccfix entry | 964 | 268 | 3 | 1 |
| before its first RESETSTAT | 964 | 270 | 4 | 1 |
| after that RESETSTAT | 0 | 0 | 0 | 1 |

The later RESETSTATs also return zero. An `arms=0` counter after resetting
statistics is not a disarmed lane. The traces are printed by the real ccfix leg.

`tools/ccfix5_probe.sh` imports the actual `tests/differ_gate.sh` boot/ownership
helpers and `GATE_DIFFER_GEOMETRY=armed-fused`. Three fresh boots **per atomic mode
per arm** all serve exactly 1,024 clean reads, report zero after RESETSTAT, then
serve another 1,024 clean reads with zero fallbacks. Every boot still reports
`thread_mode=1s read_local=1`. Each atomic=1 boot additionally opens 12/12 held
MSET windows: 36/36 PRE and 36/36 POST, with two pending entries and no writer
reply while held. This first probe isolates arming/reset behavior; it does not
replace the matrix's pending-source reader proof. Full INFO and DEBUG LBSIGNALS
dumps are in [PRE](docs/ccfix5/probe-PRE) and [POST](docs/ccfix5/probe-POST), with a
[summary](docs/ccfix5/fresh-probes.json).

There is no differing eligibility condition in this reproduction. The ordinary
parse/GET/drain selection is 272/272 raw and canonical bodies equal to merged PRE
([inventory](docs/ccfix5/read-path-audit.json)). The notification mask is copied
to `set_read_local_keymiss_notify()` by `IoLoop::refresh_notify_config()`; the
keymiss bit intentionally routes notification-sensitive reads through the owner.
Neither that code nor `Shard`'s flat sink binding differs from merged PRE;
`io_loop.h`, `ex_loop.h`, `read_local.h` and `shard.h` are source-identical.
CC11's classifier runs only after the notification observer admits a keymiss.
The classifier was not reverted: executing the unchanged POST already disproves
the assertion that it never serves a local read.

Fix: `differ_gate.sh` samples the real counters after every suite and retains
their peak observation, including a per-leg TSV. The final row explicitly
reports both the peak and final values; the peak is not labelled a lifetime
total. No synthetic reads are added. A reset cannot erase an observed hit;
zero throughout, missing/malformed counters, or a failed observation still fail.
The real shell loop is exercised by `differ_fanout_test.py`: a 0→7→0 trace passes,
all-zero and missing-counter controls fail, and no invalid completion artifact
is accepted. All 19 serverless harness tests pass
([log](docs/ccfix5/fanout-test.log)).

The mainline idle-box comparison used different workloads. The headline tree
does not register ccfix, so it executes neither the extra counter resets nor
the pending-source test. Its terminal 914 hits therefore cannot be compared to
ccfix's post-reset zero as a binary execution-rate difference. The landing and
idle logs remain valid observations; the inferred lifetime interpretation was
incorrect. No contention explanation is needed for A. See the
[retained mainline comparison](docs/ccfix5/mainline-comparison.json). The original landing
`gate-run.HrdWfH` has atomic=1 misses at seeds 7 and 23; the actual idle replay
`gate-run.zbWwPT` has a seed 19 miss. The endgame summary grep globbed all earlier
`gate-run.*` directories, so its seed list combines runs. Headline's corresponding
run is `/home/user/Projects/cx-final/build/gate-run.FsHboC`. The idle reproduction
has 914 atomic=0 hits; the other 944 value in the summary came from another run.

The actual fourteen-cell null uses `/tmp/claude-1000/generic_merit_cells.txt`,
not ccfix4's proposed headline-cell list. Its four l1 cells are d32g_l1,
d8s_l1, d32s_l1 and x9_32_l1: **32 fused threads on 0–31, 256 shards, atomic=1,
read-local=1, overlap=1, reorder=0**, 512 connections, with load on 32–111.
Their recorded boot INFO confirms the lane is armed. They do not execute CC18's
RESETSTATs or the held pending-source construction. The original argv and boot
INFO are retained in [null geometry](docs/ccfix5/null-l1-geometry.json).

## B: DEBUG hashed namespace zero after SWAPDB

`gen_multidb()` performs random SWAPDB operations before ccfix on the same server.
Its final SELECT 0 and FLUSHALL empty the data but do not restore the database
map. `multidb_stamp()` captures the mapped physical namespace in `op.physical_db`
and stamps actual key arguments (`src/cmd/multidb.cc:514`). DEBUG has no key
metadata, so its arguments retain namespace zero. Before this fix, DEBUG SHARD,
SHARDS and ATOMIC-FILTER-CELL hashed those raw arguments.

Consequently `_lib.owner_buckets()` could select two apparently different owners
while the actual MSET keys both routed to one physical shard. MSET then completed
through atomic_localfast: pending entries stayed zero and the writer replied
while ATOMIC-COMMIT-HOLD was set. This is why the 5-second polling loop could
never observe its promised window. The fault is in the geometry oracle, not in
the pending counter or fused execution.

The hold is a global Server latch checked by **each owner's**
`ExLoopT::flush_xshard_commits()` (`src/core/ex_loop.h:2757`). It holds scatter
commit queues, not the one-shard localfast path. INFO sums live pending records
from each shard in either mode (`src/cmd/t_server.cc:1891`). Changing where reads
execute does not move this accounting. The exact key choices depend on the timestamp and owner buckets; passing split
or identity-map fresh boots never established the oracle's validity after a swap.

Fresh-boot identity-map probes on both merged arms opened every window. Adding
SWAPDB 0 1 to the same armed-fused probe reproduced the failure on **PRE as well
as the uncorrected merged POST**, with the following three-boot controls:

| Arm / fixture | Boot 1 | Boot 2 | Boot 3 |
|---|---:|---:|---:|
| PRE, identity map, held MSET | 12/12 | 12/12 | 12/12 |
| Uncorrected POST, identity map, held MSET | 12/12 | 12/12 | 12/12 |
| PRE, SWAPDB, source readers | 23/24 | 23/24 | 23/24 |
| Uncorrected POST, SWAPDB, source readers | 23/24 | 24/24 | 23/24 |
| Final POST, SWAPDB, release peers after each round | **24/24** | **24/24** | **24/24** |
| PRE, matched closed-peer fixture, repeat control | 23/24 | 22/24 | 20/24 |
| Final POST, same matched closed-peer fixture | **24/24** | **24/24** | **24/24** |

Every unopened window has pending 0→0, atomic_localfast +1 and writer_ready=true,
despite distinct DEBUG-reported owners. Every final POST window has at least two
pending records, the held writer cannot reply, and COPY/SINTERSTORE/BITOP visits
the pending sources' predecessors. The documented notification deviation is
checked only after those assertions. Both atomic=0 and atomic=1 boots also
serve 1,024 clean local reads before RESETSTAT and another 1,024 afterward, with
zero fallbacks. The swapped-probe summary and complete INFO/DEBUG traces are
retained in [swapped probes](docs/ccfix5/swapped-probes.json). A separate
[validation](docs/ccfix5/final-probe-validation.json) checks all 72 final windows
for pending 0→at-least-2, unchanged localfast and an unreplied writer. The negative results
were not discarded. The additional
[matched closed-peer controls](docs/ccfix5/matched-closed-probes.json) use identical
flags on both arms: `--attempts 24 --readers --swap --close-peers`, three boots
per atomic mode, server 120–127 and clients 112–119. They ran after split
completed, alongside armed run 2. PRE still fails seven constructions through
localfast; POST opens all 72. Thus peer cleanup alone does not repair the
namespace bug. Exact failing keys vary with the generated names; these counts
are construction evidence, not a rate estimate. Additional identity-map reader controls are retained in
[pending probes](docs/ccfix5/pending-probes.json).

Fix: the three cold DEBUG subcommands copy their key Slice, apply
`op.physical_db`, and hash that copy. They use the operation's captured map;
there is no second map lookup, extra reader retry, write-path change or hot-path
branch. `tests/ccfix5_debug_unit.cc` directly compares the real DEBUG handler
against real MSET key stamping across DBs 0, 1 and 15, before and after swaps
0↔1 and 1↔15. It fails on PRE with "DEBUG SHARD disagrees with MSET routing
namespace" and passes **864 comparisons** on POST, including 192 nonzero-namespace
hashes. See [PRE failure](docs/ccfix5/debug-PRE.log) and
[POST pass](docs/ccfix5/debug-POST.log). This is a serverless, deterministic
regression proof, independent of random wire scheduling. Each arm uses its own
headers and linked objects.

The repeated source-reader probe also exposed retained connection read cuts:
leaving all round peers open eventually failed "old pending records did not
drain" after 12 successful windows. `_differ_ccfix.py` now closes each round's
writer and reader after consuming the replies and checking notification frames,
before the next FLUSHALL/drain check. The failed diagnostic is retained as
`probe-POST-swap`; with peer cleanup, all three final 24-round runs pass. No
timeout is widened and no pending-window, predecessor-read or zero-notification
assertion is removed. Failure now includes before/held counters, placement,
writer readiness and LBSIGNALS instead of an unexplained timeout.

## Hot-body and instruction proofs

The final audit reports **16,928/17,013** identical body occurrences,
**1,206/1,213** handlers, and **1,495/1,496** selected hot bodies. The seven handler
differences are the inherited six CONFIG/INFO occurrences and the new cold DEBUG
body, 6,484→6,532 bytes. The one selected ordinary difference is still
ccfix4's db0 `WbEngine::serve_impl<false,true,false,true,false,false>` lambda,
824→537 bytes. The strict audit exits 1; it is not described as a byte-equality
pass. All **85 changed occurrences** are listed in the
[complete inventory with reasons](docs/ccfix5/changed-bodies-with-reasons.json).
The [final audit](docs/ccfix5/final-audit/summary.json) retains the complete
inventory. Relative to the merged POST before this lane's fix, only the cold
DEBUG body's canonical equality changes; its wrapper also changes raw call
displacement but remains canonically equal
([delta](docs/ccfix5/ccfix5-audit-delta.json)). The upstream cd13b composition
changes some non-selected xshard helpers; those differences remain disclosed.
This lane does not waive ccfix4's writeback exception or its required owner null
decision. The ordinary read bodies remain 272/272 equal.

The unchanged five instruction witnesses pass **exact equality** for both normal
and db0 namespaces on the frozen final objects. Each row executes 100,000 calls:

| Witness | PRE instructions | POST instructions |
|---|---:|---:|
| off/keymiss | 1,800,053 | 1,800,053 |
| off/string | 1,800,053 | 1,800,053 |
| save-only/keymiss | 2,000,053 | 2,000,053 |
| save-only/string | 2,400,053 | 2,400,053 |
| note_command | 700,038 | 700,038 |

The complete CSVs and [comparison](docs/ccfix5/instruction-comparison.json) retain
both namespaces. This final run followed the DEBUG rebuild, with no server/load
overlap. The earlier full run before that correction also passed and is preserved
under `instructions-before-debug-fix`. No witness source or tolerance changed.
These are fresh merged-arm receipts; they do not rewrite ccfix4's recorded 0/11.

## Final matrix receipts

All three armed executions are complete. **Run 2 is a retained failed full
matrix**, despite every ccfix leg and pending-source window passing. It found
the GEO placement-fixture issue below; the expanded final run passes after that
fixture correction. This is two fully green matrices, not three.

| Run | Atomic=0 | Atomic=1 | Read-local peak hits (0 / 1) | Pending windows | Gate exit |
|---|---|---|---|---|---|
| [armed 1](docs/ccfix5/matrices/armed-1/receipt.json) | 216/216 | 220/220 | 981 / 981 | 15/15 | 0 |
| [armed 2](docs/ccfix5/matrices/armed-2/receipt.json) | 216/216 | 218/219 comparison legs; GEO seed 28 failed | 981 / 981 | 15/15 | 1 |
| [armed 3](docs/ccfix5/matrices/armed-3/receipt.json) | 259/259 | 263/263 | 981 / 981 | 18/18 | 0 |
| [split](docs/ccfix5/matrices/split/receipt.json) | 220/220 | 224/224 | read-local not armed | 15/15 | 0 |

Split additionally passes all **32 mode-equivalence cells**. Rows in the armed
counts include the existing non-vacuity row; split counts are comparison legs.
Failed run 2 emits `pass=219 fail=2` for atomic=1: 218 successful comparisons plus
the lane row, one GEO failure and the strict missing-completion rejection. Its
434 actual comparison legs were executed, with all ten ccfix legs passing.
No failed run is relabelled as PASS. The complete archives preserve each frozen
plan, journal, coverage artifact, ccfix leg and counter observation.

The final run automatically retains failed seed 28, so its inventory expands
to six seeds: 7, 19, 20, 23, 28 and 29. Its final counters are 0/21 hits
for atomic=0/1 after the resets, while the sampled peaks are 981/981.
Across the three armed runs, all **32 ccfix legs** pass and all **48 pending
windows** open; split adds ten passing ccfix legs and 15 held windows. Harness commits and relevant file hashes are recorded in
[matrix sources](docs/ccfix5/matrix-source-manifests.json). There are three serial
armed-fused repetitions plus one overlapping split repetition,
using the full discovered suite/seed matrix in each part. Armed servers use
112–119, load uses 120–127, and Redis 7.4 is pinned to CPU 120. To fit the
90-minute lane limit, split overlaps armed after the paired diagnosis and all
instruction counts have finished: split servers use 120–127, clients 112–119,
and Redis CPU 112, with ports 18161–18182. Server groups are disjoint but
correctness client CPUs are shared across runs. No rate/latency conclusion is
drawn from this overlap. Each target has 16 shards and 16 databases. Armed uses
eight fused threads, read-local=1;
split uses the gate ratio 6:2. This matches each landing slot's target geometry,
while the 0–83/84–111 mainline run had enough slots to execute jobs concurrently.

The exact invocation is:

```sh
REDIS74_ROOT=/home/user/Projects/redis \
GATE_DIFFER_ORACLE_CORES=120 GATE_ONLY_JOBS=differ-armed \
taskset -c 112-127 tests/gate.sh iteration \
  --server-cores 112-119 --load-cores 120-127 --load-smt '' \
  --ports 18139-18160 --candidate-binary "$PWD/build/ccfix5/POST/tomokv"
# Repeat armed three times. Split uses the same command with:
# GATE_ONLY_JOBS=differ-split GATE_DIFFER_ORACLE_CORES=112
# --server-cores 120-127 --load-cores 112-119 --ports 18161-18182
```

The GEO failure was an arming assertion **before STORE**, not a differing GEO
reply: `((13,5,1),(7,5,1))` showed distinct shards but the same current owner.
`tests/cd13b_wire.py` selected a cross-owner pair, issued 4,096 LFU-priming reads,
and assumed the old placement still applied. Load balancing could move the hot
destination during that interval. This independent fixture came from the merged
cd13b work; no GEO production body changed in ccfix5.

The final harness checks LFU and current cross-owner placement together inside
its existing three-fresh-destination arming loop. A failed arming is printed,
both keys are deleted, and the next attempt uses fresh names. After three
failures it fails with the LFU values and placement. The before/after STORE
owner/migration equality, reply, encoding and LFU-preservation assertions remain
unchanged. `tests/cd13b_window_test.py` runs the actual property with controlled
movement: the old property fails all three verbs before STORE, the fix re-arms
and passes all three, and a window that never opens fails all three after the
bounded attempts. See [before failure](docs/ccfix5/geo-window-before.log) and
[two passing controls](docs/ccfix5/geo-window-test.log). The final matrix uses
this correction and passes GEO seed 28 in both atomic modes; it does not make
the earlier failed matrix a pass. The controlled-movement test is the proof that
rearming actually executes; no spontaneous movement is required for a green
wire run.

The release/footprint prerequisite runs with each selected gate part. These are
partial correctness receipts, not a full 517-row gate or an ABBA result.

Earlier diagnostics are not counted as final proofs: `gate-run.C13Mg5` captured
the original zero after all 215 atomic=0 legs passed, but editing the harness
while its shell remained alive invalidated the tail and yielded shell errors.
Its INFO evidence is retained in `docs/ccfix5/diagnostic-matrix`. The subsequent
`gate-run.cD5XfE` attempt was deliberately terminated after discovering the DEBUG
namespace cause so the frozen final binary could be tested. Neither is reported
as a successful full repetition.

Rows remain **+0 quick / +0 full**. `tests/gate.sh` is unmodified; EXPECT values
stay 500/517. Differential collections are at lines 3392 and 3403, both after
the quick-tier exit at line 3364. No row was added or retired and no count change
is requested.

## Acceptance limits and handoff

The requested three armed executions have positive read-local witnesses and all
ccfix legs passing. They are **not three clean full-matrix receipts**: run 2 is
red on the separately corrected GEO fixture. Only run 3 uses the final GEO
fixture; two additional armed repetitions would establish three fully green
runs of that final harness. They are left to the maintainer within the lane's
90-minute limit. The strict ccfix4 writeback-body exception also remains for the
maintainer's explicit null/acceptance decision. No EXPECT value was changed,
no failing artifact was discarded, and nothing was pushed.
