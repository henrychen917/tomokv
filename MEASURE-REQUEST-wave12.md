# Wave 12 integration and measurement request

## wave12 integration

Integrated on `cx-wave12`, based on headline `e32b04a44`. No push.
Owner approval D12 authorizes design A. The three lane reports, including
flushfix2's inherited findings and the design review, were read before merging.

Merge order: `15acf5102` (cx-flushfix3), `83b29aaa5` (cx-trackorder),
`3adae5254` (cx-maxmemrace), all with two-parent `--no-ff` merges.
Only the FLUSH merge conflicted, in five Makefile inline budgets. The initial
resolution preserved both source changes and applied the additive budget
deltas; the compile-only trials below then selected the final budgets.
Lane branches remain untouched. Neither flipfix6 nor execfifo2 was merged.

All builds and authorized correctness work use CPUs 64–95 and ports
20000–20099. Performance measurements, load generators and the full iteration
are reserved for the maintainer. No throughput claim is made.

The row census, named-skip sweep, binary builds, compiler trials, instruction
census and production-unit freshness proof are complete. EXPECT_QUICK/EXPECT_FULL
remain unchanged. The shared-body identity exceptions and PAD-A's aggregate
layout limitation are explicit below; merit remains the maintainer's decision.
The authorized correctness matrix passed all **362/362 required job/geometry
entries**. The full iteration and performance work listed below remain NOT RUN.

### Exact source-declared rows

The headline declares 977/994. The merged source declares **999/1016**, DQ=DF=+22,
with no removed label. `docs/wave12/row-inventory.json` records every row against
its collector LINE and the quick exit. Flushfix2 adds 14 directed + 2 lifecycle
rows, flushfix3 adds 4, trackorder +1, maxmemrace +1. All are before the quick exit.
The owner should set EXPECT_QUICK=999 and EXPECT_FULL=1016 at landing.

| Added declaration | Rows | Collector line in `tests/gate.sh` |
|---|---:|---:|
| flushfix3 idle, two namespace configurations | 2 | 6145 |
| flushfix3 lifecycle units, both namespaces | 2 | 6146 |
| flushfix2 seven directed cells × two namespace configurations | 14 | 6147 |
| flushfix2 lifecycle units, both namespaces | 2 | 6148 |
| maxmemrace | 1 | 6387 |
| trackorder | 1 | 6394 |

Every collector precedes the quick-tier exit at line **6464**. The total is
22 added quick and full rows; Tcl promotions change assertions inside existing
rows and add no public row.

The initial source census falsely reported 1001/1018: gate_ledger_fixture ignored
conditional assignments in job_flushfix2, inventing ASYNC legs for three cases
and omitting FLUSHDB. The integration writes the same seven case/command/mode
combinations explicitly, extends the static parser's finite split grammar to
colon-separated cells, and adds a directed 14-label product check. Runtime
coverage and row count are unchanged; no test was removed. The checked-in label
fixture now matches the actual declarations, including FLUSHDB. The earlier
incorrect inventory remains visible in commit 787fd64ae.

### Semantic interactions

- R3 range conflict detection remains on the script validation path. Cached
  script metadata owns immutable source/flags; the persistent interpreter's
  activation context is rebound for each run. Neither cache substitutes for
  the current activation cut, so a retained compiled body cannot hide FLUSH.
  PAUSE classifies scripts from the same no-writes metadata before execution;
  FLUSH is classified as a write and its range does not mutate script flags.
- The FLUSH unit retains atomic admission through collapse. FLIP/LB drains
  therefore wait for its admission to retire. Wave11's stage actions still
  use flip_stage_owed; the FLUSH continuation wake remains unconditional.
  The final live witness passed all eight target legs (both engines, atomic
  settings and namespace configurations), with positive FLUSH/FLIP counts,
  zero refusals and clean child exits. Both Redis oracle legs also passed.
- climon_flush_completed still runs at ROB retirement after all shard effects
  finish, before reply assembly, with the originating Op still Done. Thus the
  trackorder helper sees the intended SYNC/default boundary; ASYNC retains
  deferred OOB emission. Separate REDIRECT streams have no total byte order.
- CONFIG remains an AllShards operation, separate from Kind::Flush. Every
  fragment applies the latest memory configuration on its current owner;
  configure_maxmemory changes admission/eviction settings, not range records,
  floor eligibility or poison lifetime. Existing MVCC guards keep eviction
  from destroying retained FLUSH preimages. No added fragment discriminator
  reaches ordinary GET/SET/INCR.
- The central reply-builder audit is extended in docs/crlffix/audit.md and
  wave12-added-sites.json. No new raw error/status writer was found.

### Delivered binaries and layout control

Production source is frozen at `5a9f38173`; subsequent changes are harness and
evidence only. `build/tomokv` equals the frozen POST. All three arms were built.

| Arm | Worktree path | SHA-256 |
|---|---|---|
| PRE, source e32b04a44 | `build/wave12/tomokv-PRE` | `02796cdccee7fd16ffaa0dff2633b0d5c30ecdf3c59d404b5a2bb6135a764e48` |
| POST | `build/wave12/tomokv-POST` | `bded27b18371edf7a43df171f042444d6c7f6d34c2fe2bd87f6b83b13c9356d4` |
| PAD-A | `build/wave12/tomokv-PAD-A` | `aee862288a87c0ea45eeb3f2b9ef5c367b0366fb3c88bc2849669583499fd647` |

The rebuilt PRE's `.text` and `.data` exactly equal the supplied headline.
Its `.rodata` differs only in the two eight-character INFO build identifiers;
[the binding](docs/wave12/pre-binding.json) records the supplied headline hash.

PAD is **(A) behaviour twin**: PRE behavior, inert POST `GroupAux` fields,
POST's `.text` origin/extent and `.tbss` size. PRE text is 8,729,431 bytes;
POST/PAD-A text is 8,850,599 bytes, both starting at 182,960. The TLS control
adds 32 unused bytes, accounting for both namespaces. Individual function and
data addresses are not matched. This is the same limited aggregate layout
control used by the lanes; it cannot isolate every cache-placement effect.
[PAD recipe and section receipts](docs/wave12/pad-a.json),
[final arm manifest](docs/wave12/arms.json).

### Compile-only budgets and body identity

There were 301 distinct compile trials across 59 pinned objects and 155 linked
candidate audits. The selected changes from the initial merge are normal
`t_server` 33583→33750 and normal `rl2s` 164680→164705. The db0 `t_server`
budget stays 34177 to preserve maxmemrace's CONFIG body; the generic residual
score alone preferred a budget that lost that identity.
[All trials and selection](docs/wave12/budgets/final-selected.json).

All 12 dedicated GET/SET and captured-local-MGET bodies equal the headline.
The explicit mechanism check finds 36 FLUSH/R3 bodies equal to flushfix3,
two invalidation-order helpers equal to trackorder, and 12 CONFIG/apply bodies
equal to maxmemrace. [Focused body proof](docs/wave12/identity/focused-bodies.json).

The strict whole-binary inventory is 10,279 groups: 9,292 headline-identical,
828 changed groups identical to a lane POST, and 159 residual groups. Twenty-five
residuals have identical encoded instructions and equal eight-byte constants;
only objdump's neighboring-symbol labels differ. The strict count is retained.

Exact identity is **not complete for shared bodies**. Of 88 command-hot groups,
54 equal the headline, 22 equal a lane and 12 are residual scatter/dispatch
groups. FLUSH's normal `flush_redispatch<false>` outlines `note_lane_full`;
db0 `execute_flush` outlines `atomic_read_floor`. These two lane bodies do not
equal the isolated FLUSH POST. FLIP bodies retain wave11's `flip_stage_owed`
and stage actions, which are absent from flushfix3's wave10 base. Shared
dispatch combines FLUSH routing, CONFIG owner binding and wave11 script/PAUSE
handling. No body was made identical by removing an approved behavior.

[Every changed body and its reason](docs/wave12/identity/changed-bodies.md),
[exact residual instruction diffs](docs/wave12/identity/residual-instruction-deltas.json.gz),
and [the full census](docs/wave12/identity/summary.json) retain these exceptions.
Identity remains a proxy; the maintainer's merit run decides acceptance.

### Serverless integration-cost proof

The production-object fixture counted 244 native cells and 96 Lua-inclusive
warm-script cells. It covers both modes/namespaces, atomic 0/1, batches 1/32,
read-local GET, EXEC with 1/2/4 children on one/cross shards, warm EVAL/EVALSHA
(plus FCALL), and empty/eight-key FLUSHALL. Every executed native body and
assembly stub binds to production: final native 696 and Lua 432 checks, zero
mismatches. PRE also binds to the supplied headline, including 87 FLUSH checks.

| Activation family | POST−PRE instruction range across requested cells |
|---|---:|
| GET | −1120 to 0 |
| SET | 0 |
| INCR | −1248 to 0 |
| Read-local GET | 0 |
| MGET | −11008 to −6 |
| MSET | −54824 to −9 |
| EXEC, one shard | −326 to −23 |
| EXEC, cross shard | −310 to −47 |
| Empty/small FLUSHALL | +36877 to +37762 |

These are totals per activation, including the batch, not cycles or rates.
GET/SET/INCR execute zero added instructions. The db0 GET/INCR reductions are
35/39 instructions per operation in these scopes. Native EVAL/EVALSHA can add
1–25 instructions versus wave11 in normal-namespace cells: the FLUSH kind
classification, range-aware scatter lifecycle and compiler outlining account
for the decomposed changes. Against the retained scriptfix3 reference, **all
EVAL/EVALSHA native and Lua-inclusive cells are no higher**. The extra FCALL
control has four small positive comparisons, at most 11 instructions; it is
reported rather than folded into the EVAL claim.

FLUSH's added work is the approved atomic range unit, epoch/participant
publication and collapse lifecycle. The census excludes shared-library
instructions, networking/syscalls and idle-loop work; its fixture uses no live
server. [Every cell](docs/wave12/instruction-comparison.md) and
[every delta's exact function decomposition](docs/wave12/instruction-comparison.json)
are retained. The scriptfix3 comparison uses wave11's bound historical receipts;
that reference was not rerun in this wave. No throughput conclusion follows.

### Tcl skip sweep and manifest interactions

All **259** original named skips received three fresh isolated attempts in
each mode: **1,554 attempts**, no missing-assertion passes. Forty-five names
(58 assertion occurrences) passed all six attempts and were promoted. The
manifest now requires **1,875** occurrences across 37 files and retains 214
named skips. The three lane merges themselves changed no manifest counts.
[Per-root retained failures](docs/wave12/tcl-skips/README.md),
[full sweep summary](docs/wave12/tcl-skips/summary.json.gz), and the numbered
compressed receipts retain every attempt.

Of the historical 23 SCRIPT-UNDECLARED-KEY names, three were already required
passes on the headline; 15 of the remaining 20 pass and are promoted. Five
still fail: the function MONITOR case, Lua-number conversion, trim-string,
write-on-OOM and script-tracking cases. Their current first failures are listed.

The first full manifest run exposed two harness interactions. The promoted
slowlog trimming assertions inherited `slowlog-max-len=0` from the retained
zero-capacity test while their restoring predecessors were skipped. Existing
`isolated_tests` support now requires both unchanged assertions on fresh servers.
The WATCH cross-connection ordering retry was also disabled by a separately
declared block-setup error. It now permits one fresh retry of either named
ordering assertion while preserving exact setup-error accounting. Seven
negative controls reject missing, duplicate, still-failing or unrelated
assertions, unknown setup errors, incomplete runs and timeouts. No assertion
was deleted and no tolerance widened.
[Initial failures and directed controls](docs/wave12/tcl-sequence-findings.json).

The final harness was also tested with the planted CLIENT-LIST-CMD-NAME
regression through the complete Tcl gate job in both modes. Both jobs failed;
only `unit/introspection` failed, including the intended CLIENT LIST command
name assertion. All other manifest files passed. The mutated source and binary
were confined to a throwaway build and removed after recording their hashes.
[Both negative-control attempts](docs/wave12/isolated-regressions.json).

The final quiet complete Tcl job passed **1,875 required assertions in each
mode**, with all 37 files and the two isolated slowlog executions present.
The retained setup errors are still accounted for exactly. The proof reuses
the runner's assertion-multiset validator and binds the same final runner and
manifest to both positive runs and the planted negative control.
[Final Tcl proof and compressed receipts](docs/wave12/tcl-final-proof.json).

### Correctness receipts

The final [coverage verifier](docs/wave12/correctness-coverage.json) passed:
362/362 required job/geometry entries, 281/284 registered jobs, and both control
arms booted in both modes. The three unselected registry entries are the two
reserved performance jobs and the build-only tailgen prerequisite described
below. No required correctness job is missing.

The source-row multiset has evidence for **1009/1016 declarations**: 1007 from
complete passing job ledgers plus the two official strict differential folds.
All 21 duplicate AOF declarations retain their multiplicities; extra geometry
repeats cannot fill a missing declaration. The seven remaining rows are exactly
the reserved performance/load-generator rows below. This is not a full-gate
pass. [All attempts, including failures](docs/wave12/correctness-jobs.json).

The primary whole-job invocation completed **269 jobs, 993 passing row
executions and zero failures**, on the frozen POST. It is a selected partial
invocation, not an iteration receipt. Production source and binary hashes were
stable throughout. Only the Tcl runner, manifest and Python harness tests
changed during it; the affected jobs were excluded from this invocation and
are replayed separately. [Primary receipt](docs/wave12/jobs/landing-main-2s-uring.json),
[exact harness delta](docs/wave12/primary-harness-delta.json).

The primary campaign has passed all 14 FLUSH rows: 112 target legs and 14 Redis
oracle legs. Every target leg also passed the directed cached-EVALSHA / retained
range / CONFIG interaction, with positive range-read, post-version, script
conflict, slow-collapse and chunk-cache-hit counters and final script result
`[1,1]`. Failed arming would exhaust bounded fresh attempts and fail the row.

Tracking order passed **20,736 target cases** (24 geometries × 864) against
864 Redis 7.4 oracle cases. This includes FLUSHALL/FLUSHDB, default/SYNC/ASYNC,
RESP3, RESP2 REDIRECT, RESP3 REDIRECT, pipelining, own/other connection,
NOLOOP and tracking modes. Complete per-stream bytes match the oracle;
independent REDIRECT streams are not assigned an artificial total order.

The maxmemory row passed all **48 target geometries** and the oracle, three
trials per case. Every target witnessed its required open window. No failed
OOM/admit/evict assertion was observed. The complete leg inventories, raw JSON
archives and hash bindings are retained in
[the complete interaction proof](docs/wave12/semantic-runtime-proof.json).

The final flushfix3 idle job passed all 16 legs and all **64,000** recorded
calls against its existing 5 ms deadline. This is the requested correctness
job; it is not the populated-FLUSH latency merit instrument. The final
[live-FLIP witness](docs/wave12/final-flip.json) uses the delivered POST and
retains all eight target legs and both oracle legs.

The standard differential suites passed on both io_uring and epoll. Each engine
ran all 47 suites, permanent seeds 7/19/20/23, its selected rotating seed,
the four mandatory seed-19 MULTI repeats and all 16 mode-equivalence cells.
The gate's own strict public folds validate **490 split + 464 armed = 954
comparisons per engine**, including complete journals. These are the two public
rows whose private child jobs are selected through the partial job interface.
[Differential proof](docs/wave12/differential-proof.json).

The additional mode/engine replays, atomic-0 script bounds and all four atomic
battery geometries passed. Eight complete stream feature-job replays retain
all three release memory bounds, giving 24 checked assertions. PRE and PAD-A
each passed the gate's dbdefault boot/control job in both thread modes.

`make all` and all production-unit builds/freshness queries passed: 64 checks,
including the 55 production-unit targets/arms, the two mdbqsbr live arms,
blockfix cost binding, blockfix2 and both namespaces of flushfix2/3. The complete
commands and `make -q` results are in
[production-units.json](docs/wave12/production-units.json). The final
[`make -q all` check](docs/wave12/final-freshness.json) also passed; production
source has no delta from the frozen POST.

The initial Tcl promotion run failed on the two manifest interactions above.
The next run passed all 1,875 required occurrences in 2s; 1s hit the unchanged
upstream Lua GC watchdog while other correctness stress jobs were active
(also failing compat2's dependent public row).
The first Python harness run likewise hit its unchanged one-slot watchdog
during concurrent compilation. These attempts are retained. The final quiet
Tcl jobs and all **83 tests in `python3 tests/gates_test.py` passed**, with
unchanged deadlines. [Final sequential-stage receipt](docs/wave12/final-correctness-stage.json),
[Python test output](docs/wave12/final-harness/final-gates-test.log).

The first complete ABBA self-test exposed one stale serverless fixture in
`redis_tcl_test.py`: it supplied the tuple of two allowed WATCH ordering names
as though it were one assertion name. The fixture now exercises each name,
retaining its complete-pass, missing, duplicate, timeout and unrelated-failure
controls. Its ten tests pass. The live Tcl runner, manifest and server binary
did not change; their positive and planted-regression bindings remain valid.
[Failure and directed fix](docs/wave12/abba-fixture-fix.json).

The complete ABBA self-test then passed through the gate job interface,
including the 83 scheduler/harness tests and ten Tcl controls. Landing EXPECT
overrides were confined to a throwaway copy carrying the prepared label
fixture; the tracked constants remain 977/994. The copy comparison, failed
first attempt, passing replay and full raw control log are retained in
[the final harness proof](docs/wave12/final-harness-proof.json).

### Artifact retention

`build/` finishes at about **32 GiB**. The three delivered arms and current
production/unit outputs remain available. Superseded trial objects, initial
arm, PRE/PAD source trees, throwaway self-test source copies and instruction
step traces were removed after recording hashes and counts. Complete job
ledgers remain at their receipt paths; raw lane/Tcl/differential evidence is
also archived under `docs/wave12/`. The pruning manifests are
[trial artifacts](docs/wave12/pruned-trial-artifacts.json),
[instruction traces](docs/wave12/pruned-instruction-traces.json),
[final build artifacts](docs/wave12/pruned-final-build-artifacts.json), and
[the final self-test copy](docs/wave12/pruned-abba-final-copy.json).
The [delivery check](docs/wave12/delivery-check.json) verifies arm hashes,
archived proofs, unchanged production source and EXPECT constants, and no
remaining lane servers or listeners on ports 20000–20099.

### Checks reserved for the maintainer — NOT RUN

The performance-only `flip_saturated` and `efficiency` jobs were not run. Their
public rows are FLIP under saturated load and its coupled shutdown check,
expire-index growth, borrow-registry growth and cross-shard dispatch scaling.
The atomic MGET/MSET throughput floor and inline tailgen client-LB outstanding
bound were also not run. These seven public rows require the performance work
or load generators reserved for the maintainer; they remain in the 999/1016
landing declaration and label fixture.

The `atomic_floor` job's tripwire and 400-roll program-order checks passed with its
existing correctness-only switch. Atomic RYOW rate assertions and XMOVE
size-ratio timing assertions remain NOT RUN under that switch. Stream's three
release memory bounds passed in additional complete feature-job runs with the
normal release assertions enabled; those jobs invoke no throughput benchmark.

An explicit attempt to select `tailgen_build` alone was rejected by
`gate_subset.sh`: it is a build-only prerequisite whose only consumer is the
reserved inline load-generator check. The rejection receipt is retained.
The full `tests/gate.sh iteration`, wave null, fixed-anchor race, EXEC/script
merit, FLUSH latency merit and writer-wait instruments are NOT RUN here because
the task reserves them for the maintainer.

### Maintainer measurement request — NOT RUN here

Use the frozen arms above and the gate's existing matched-offered-load
instrument, acceptance rules and reviewed geometry. Retain contemporaneous
identical-arm nulls. Rate at matched offered load is the verdict; cycles/op,
instructions/op and IPC explain it. Require zero main-command regression.
PAD-A should remain flat when attributing an improvement to behavior. Scatter
above 2% on identical arms invalidates the run for investigation.

1. Wave null: POST versus supplied headline `e32b04a44`, the unchanged 28 cells
   in `docs/wave12/cells/null28.txt`. Use three blocks for p8g, h05 and h06;
   retain the standing three-block notify_exm control and other cell settings.
   Include the rebuilt PRE/PAD-A pair as the labelled layout control.
2. Fixed-anchor race: POST versus
   `/home/user/Projects/bench-bins/tomokv-headline-991d48f65`, with the generic
   fourteen and nine read-local cells in `docs/wave12/cells/`, plus EXEC below.
   Keep this three-block comparison separate from the wave null.
3. EXEC: `/home/user/Projects/calib/exec-merit.py`, PRE/POST,
   `--conns 64 --threads 16 --cells all --blocks 3 --secs 20`. Preserve all
   eight mode/atomic/uncontended-hot cells, pipeline four, two INCR children,
   four competing writers in hot cells, the driver's balancing/FLIP settings
   and one hashed benchtxn. Require zero order violations; keep EXEC and plain
   writer results separate.
4. Contended script: `/home/user/Projects/calib/script-storm-merit.py`, PRE/POST,
   `--blocks 3 --secs 30`. Preserve T6: 2s 6:2, 16 shards, atomic 0, databases=1,
   two owners, eight EVAL clients, four EXEC, four WATCH/EXEC and four plain
   writers. Require exact final values and zero refusals/order violations.
5. FLUSH latency: `calib/flush-latency-merit.py`, POST/PRE/PAD-A with
   `--third-kind behaviour-twin --blocks 3 --populations 0,1000000,10000000
   --trials 100 --empty-trials 1000`; retain both modes, namespaces, atomic
   settings and SYNC/ASYNC. Preserve RTT and RSS boundaries separately.
6. Writer wait: `calib/flush-writer-wait.py`, the same three arms and PAD kind,
   `--blocks 3 --population 1000000 --schedules same-key,disjoint-key,no-flush`.
   Preserve matched offered load, calibration, percentiles and the single
   worst stall. D12 accepts about 1.5–2× the old single worst populated-flush
   writer stall; it does not authorize percentile or main-command regression.
7. Landing gate: owner applies **999/1016**, retains the prepared label fixture,
   and runs `tests/gate.sh iteration`. Partial jobs here do not certify that gate.

For instruments above, explicitly select scheduled CPUs and ports; do not use
their defaults while other lanes run. `docs/wave12/measurement-inputs.json`
binds cell files, driver sources and anchors. No performance benchmark or full
iteration has been run by this lane.
