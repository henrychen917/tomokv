# Wave 6 landing

## wave6 integration

Integration branch `cx-wave6`, headline `ef5204b2e`; no push. Integration and the
available correctness jobs are complete. The maintainer's null and landing
measurements remain outstanding; identity and PAD limitations are recorded below.
All builds and correctness work are restricted to CPUs 64–95, ports 26800–26899.
No performance generator or full iteration is authorized or run by this lane.

The six reports were read before their branches were merged, in the requested order,
with `--no-ff`: execfair, notifycompat, serverfix, dispatchfix, datafix1, prefetch.
Final branch states, including maintainer commits, are retained.
The writers-first information switch and executable POST-ALT plumbing are deleted;
historical receipts remain attributable. The supplied prefetch DELETE patch applies
without modification. Full-file equality to its isolated source conflicts with retaining execfair/serverfix
changes in the same files. Applying the supplied patch to the isolated branch is
byte-for-byte identical to its DELETE source in both touched files; the merged
files retain the other lanes. `docs/wave6/prefetch-delete.json` records both facts.
This is a necessary exception to the literal whole-file-equality requirement,
not a claim that the merged files are identical to the isolated lane.

### Row accounting

Headline 739/756 plus execfair 1, notifycompat 8, serverfix 8, dispatchfix 5,
datafix1 7, prefetch 0 gives **DQ=+29, DF=+29; required counts 768/785**.
`EXPECT_QUICK` and `EXPECT_FULL` remain 739/756, untouched. The fixture has all
785 declared full labels with their multiplicities; dispatchfix's five missing
fixture entries were added explicitly. `docs/wave6/rows.json` records every added job’s collection line against the
quick-tier exit (line 5335) and independently compares the source-declared label multiset.
The new gate mode hooks add no rows.

### Merge decisions and interaction audit

- OBJECT: retain notifycompat's non-touching/non-notifying lookup for all children;
  it also preserves dispatchfix's missing-key-before-policy precedence.
- XGROUP: dispatchfix moves option validation before lookup; its moved parser already
  contains wave 5's canonical ENTRIESREAD parser and exact negative-value error.
  The duplicate old parser was removed; wave 5's other stream fixes remain.
- CONFIG: retain serverfix's whole-parameter-list validation and enum parser;
  add datafix1's locale validation and publication. `Config::locale_collate` consumes
  eight additional reserved bytes after wave 5's hz fields; existing fields stay put.
- First merged build caught datafix1's static BITFIELD bound referring to the
  configuration range widened by wave 5/netfix. The assertion now uses the actual
  representable storage limit. The CD4.10 row additionally configures LONG_MAX and
  checks both sides of that limit without allocating a giant value; all legs pass.
- Slowlog: recorder creation already follows the threshold. Serverfix additionally
  moved a max-length atomic load onto every exact recording attempt; moving that
  load after the threshold is the targeted fix. Recorder lookup/creation and identity
  capture still precede Done. SV4.14 passes every leg, including a new armed but
  below-threshold GET/SET/INCR allocation snapshot and the existing enable/disable
  and negative-control legs. The recording helper's fast trace is 75 instructions
  in the headline, 78 in the initial merge, and 75 after the fix.

### Semantic pair review

- EXEC scheduling / scatter notifications: promotion changes which owner-local
  unit is retried, not when its fragment executes or decides. Pinned blockers
  retain their epoch/abort/reference lifetime; clearing them accompanies final
  reservation release. Scatter and MULTI notification batches remain attached to
  their operation, and publication/retirement follows the existing decision.
  `job_execfair` now runs `wave6_exec.py` in all eight mode/atomic/engine legs.
- EXEC / encoding transitions: list repacking and SPOP's set transition remain
  in the owner command handlers under the existing atomic replacement scopes.
  The new check runs LTRIM and SPOP across two actual owners inside EXEC, checks
  both encodings and exact remaining data, and rejects duplicate popped members.
- EXEC / container ACL: queued child validation and the execution-time ACL
  recheck remain before the child handler. The directed check covers missing
  XINFO precedence, an allowed OBJECT child, a denied child, and EXECABORT.
- Lazy logs / wave 5 / teardown: below-threshold recording never reaches the
  lazy recorder or directory fallback. The client catalog registers on its IO
  thread and protects cold snapshots/mutations with the existing catalog mutex.
  Published recorder/ACL stores survive CONFIG disable/reset and are reclaimed
  only at static teardown, after worker joins. The existing completion unit
  checks cover identity capture before Done; the broader gate jobs exercise shutdown with both log stores.
- Uniform buckets / persistence / balancing / read-local: the router and shard
  range construction share the floor-map/inverse-ceiling boundary. Balancers
  move those ranges rather than reconstructing the old quotient mapping;
  read-local and DEBUG SHARDS use the router. Non-divisor persistence uses a
  versioned map, and v1 recovery filters overlapping old sections into the new
  owner ranges. The router job passes its legacy snapshot/AOF recovery legs.
- Notifications / tracking / blocking: key-miss records are excluded from
  invalidation; real mutations retain the batch tracking stamp. Redirect failure
  acknowledgments carry their tracking configuration generation and cannot
  disarm a replacement configuration. Expired-store completion retains its
  publication-chain lifetime. The new EXEC check requires exactly two ordered
  changed-bit notifications and no no-op SETBIT event, then wakes an observed
  BLPOP waiter exactly once. All eight legs pass.
- Prefetch / execfair: DELETE removes only the unused fallback walk and its two
  calls. The fused owner walk and stale-task ownership check remain. Fast-unit
  service and pinned-blocker lifetimes do not depend on the removed hint walk.

These reviews found one source-level integration defect (the BITFIELD assertion)
and compiler propagation into ordinary integer replies. Moving WAIT's reply out
of the parser removed main.o's rvalue integer-reply template, selecting xshard.o's
smaller weak definition and adding 11 instructions to INCR. An explicit template
instantiation restores the headline definition without changing the formatter.

The first combined row run was **29 pass / 1 fail**, counting its release
prerequisite: all lane assertions passed, but one EXEC split/epoll pre-teardown
dump observed a locally closed connection whose EOF had not yet been handled.
The integration check now half-closes and requires server EOF before returning;
the unchanged shutdown assertion then passes in the complete eight-leg EXEC job.
No sleep, relaxed bound, skipped witness, or EXPECT edit was used. All 29 newly
added rows have a passing complete-job execution on the current candidate.

### Integration checks discovered by the broader gate

The R7 job exposed an error in the first integration inventory assertion: +1 is
notifycompat's **net** normal-runtime change. It replaces the old scan body with
a hot/cold unique-key pair (+2−1), while the DB0 pair already exists. The check
now requires all four named bodies exactly once, rejects the retired normal scan,
and removes each of the four in separate negative controls. Total ordinary
physical bodies remain **156 normal / 156 DB0**: headline 152/153 + execfair 3/3
+ notifycompat 1/0. Frozen-link inventories are in `docs/wave6/r7-inventory`.

The multidb owner unit raised SIGFPE in `legacy_routing(version=1, shards=0)`.
Its synthetic AOF plan populated section contents but omitted `shard_count`;
EX4.17 now consumes that metadata to select the recovery map. Production
`aof_read_plan` populates and validates the count. The unit now supplies the
snapshot's actual shard count, retaining every replay/data/map assertion.
`build/wave6/multidb-fpe.log` contains the diagnostic stack. The complete R7 and
atomic-unit jobs now pass (28 directed rows plus prerequisites); neither initial
failure is counted as a pass. Standalone `tests/gates_test.py` also passes its
quiet rerun on CPUs 64–95, port 26897.

The legacy release, notification, auth, DUMP/RESTORE, zero-copy, AOF, snapshot
and AOF-framing jobs now accept the existing `GATE_TXN_FUSED=1` selection.
The persistence knob check validates fused thread and shard-owner counts;
the two rewrite-matrix subdrivers also select fused boots. Default split
geometry is unchanged. The historical rewrite subdrivers retain their declared
4:4 split on eight cores; ordinary gate boots use 6:2 and 16 shards. Complete
fused debug and sanitizer jobs are also selected. No standalone substitute
driver or reduced assertion set is used.

### Compiled bodies and instruction scope

`docs/wave6/identity/changed-bodies.md` lists every changed body, and
`docs/wave6/callsites/summary.json` compares every residual hot group's calls
against all frozen lane links and the headline. Old-base dispatchfix/datafix1
changes are attributed against their own PRE links, not against wave 5.

The current strict inventory contains 9,406 groups: 7,710 equal the headline,
1,221 changed groups equal a lane link, and 475 remain different. Among 565 hot
groups, 428 equal the headline, 97 equal a lane, and 40 are residual composites
or compiler/layout differences. Of the 12 selected GET/SET/MGET/MSET groups,
nine equal the headline; normal `prepare_captured_local_mget` equals execfair,
and the two notification-enabled SET handlers equal notifycompat. No selected
command group is an unattributed residual.

Compile-only budget trials and linked scoring are in `docs/wave6/budgets`,
`docs/wave6/budgets-dispatch`, `docs/wave6/budgets-final` and
`docs/wave6/budgets-timed`. Final trials recompile all eight executor units on
the final source and retain every selected budget. The explicit integer-reply instantiation prevents
the measured-in-instructions weak-definition flip. The two EXEC-only outlined
helpers remove ordinary dispatch's initial +6 instructions/op in 1s and +2 in
2s. They retain the promotion callbacks and execute/Done ordering.

Final `large-unit-insns` selections (including retained ties):

| Unit | Normal | DB0 |
|---|---:|---:|
| `cmd/climon` | 26265 | 26780 |
| `cmd/t_server` | 32703 | 33074 |
| `cmd/t_set` | 26200 | 26400 |
| `cmd/t_zset` | 33447 | 32984 |
| `cmd/geo` | 14410 | 16457 |
| `cmd/xshard` | 145327 | 144177 |
| `main` | 147428 | 147449 |
| `core/genthread` | 132011 | 132813 |
| `core/rl2s` | 165332 | 163824 |
| `core/reorder` | 149814 | 150803 |

Unlisted budgets retain the headline values. The string-handler include now
has an explicit Makefile dependency for both armed units, preventing stale
objects after edits to `t_string.cc`.

The complete **64-cell serverless matrix** is in
`docs/wave6/instructions/counts.md`, with aggregate per-body/address counters,
compressed instruction traces, production provenance, and build/link commands.
These are named Tomo instruction counts, including inline code; external
library callees and fixture glue are excluded. They are not rates or cycles.
Both compiled database runtimes are exercised with their actual configurations
(normal=16 databases; DB0=1), both modes, batches 1/32, default slowlog 10000 µs
and disarmed −1. MGET uses eight keys on eight shards, atomic 0/1, batches 1/8.
Exact replies are asserted outside the counted region; a synthetic clock keeps
debugger overhead from fabricating slow commands.

**All 48 plain cells execute zero added instructions:** 44 equal PRE and the
four armed singleton fused SET/INCR cells save one instruction. The recorder
helper is 75 instructions on PRE and POST (78 in the initial merge). The last
+1 fused GET residual was a compact-body jump; the final compile-time
`Timed && Fused` hint keeps its no-hazard fallthrough contiguous. Applying that
hint everywhere added one instruction to ordinary split writes and was rejected.
The initial merged arm fails the zero-added assertion in every plain cell.
Normal MGET remains +4 instructions per key from the accepted notifycompat
owner-scatter change; DB0 MGET is unchanged.

The probe provenance verifies each actually entered body against production.
For two DB0 helpers, the strict normalizer retains an anonymous switch-table
address. A supplementary check verifies every case destination and every
instruction/encoding; altered-target and altered-bound-branch controls fail.
No register, opcode, field offset or source-line immediate is discarded.
The excluded library-call footprints and synthetic-clock call counts are also
equal between PRE and POST in all 64 cells; see
`docs/wave6/instructions/library-call-footprints.json`.

Exact isolated-lane identity is not reached for every composite body. The
40 residual hot groups are individually explained in
`docs/wave6/callsites/review.md`. Remaining parser cleanup/inlining propagation,
the DB0 R7 shutdown-helper inline choice and the read-local epoll loop still
need the owner's merit verdict. A source-pinning trial of the three read-local
helpers increased residual hot groups from 40 to 65 and was rejected; its
exact patches and input hash are retained in `docs/wave6/inlinepins-trial.json`.

### Build arms and maintainer measurement

`make all` and every `job_production_units` target completed. After all jobs
finished, all 45 `make -q` checks (the 44 requested targets plus `build/tailgen`)
exited zero; the POST hash stayed unchanged. See
`docs/wave6/correctness/freshness-final.json`. Compiled layout assertions retain
all eight locks: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944,
Rob<64> 192, AtomicEntry 144 and Config 624 bytes.

| Arm | Binary | SHA-256 |
|---|---|---|
| Frozen headline | `/home/user/Projects/bench-bins/tomokv-headline-ef5204b2e` | `95798c8e28a01583c83f434a6ecc8e8e0602e7fc1d877a94ae58ec16bebbad41` |
| Rebuilt PRE | `build/wave6/pre-source/build/tomokv` | `9388e045f35736ce08a9b9635fb83e37f5fff75c0de0c78c091a8e5969b883ee` |
| Merged POST | `build/tomokv` | `6f62f03b645852e12defd123215062b8ae44e8c74b1add2f3a5921b983d8e036` |
| PAD-A | `build/tomokv-wave6-PAD-A` | `d3c042b755ce0ec0fb6fe377e9ee6a66d02b88a1b4f15b09c75bf7b6322c5d45` |

`docs/wave6/final-artifacts.json` verifies these hashes and that production
source and Makefile are unchanged since `f1f9dc18e`; subsequent commits change
only tests, integration drivers and receipts.

PAD is **kind A, behaviour twin**: unmodified PRE object code with inert padding
matching POST's `.text` origin and total size. Its per-function offsets and data
sections retain PRE layout; it is a section-placement/size control, **not an
exact per-symbol/data-layout twin**. `docs/wave6/pad-a.json` records every input
object, the link command, padding, section sizes and this limitation.

The maintainer owns the quiet null and landing gate. Verify the arm hashes
before and after each run; retain the standing gate's null, ABBA variation and
rejection rules. Use the same offered load and declared geometry for each arm.
`docs/wave6/measurement-cells.json` freezes every recipe file, hash and cell ID.

1. Run all **181** recipes in `tests/headline_cells.txt` (SHA-256
   `f62b7a4c59cb8a9844d0baafeb19c0328f2e6790ca6103dffb21abb5ee0e20f6`),
   not only the smoke subset. Arms: headline→headline null, headline→POST,
   headline→PAD-A. Use each recipe's rate/latency verdict; retain per-cell
   cycles/op, IPC, instructions/op and latency tails. Also compare the rebuilt
   PRE with the frozen headline as a build control before attributing PAD effects.
2. Run execfair's frozen 14 generic, 14 multi-key and eight MSETNX/MSET recipes
   (`docs/execfair/cells/{generic14,multikey,execfix}.txt`) for headline→POST
   and headline→PAD-A. These include read-local off/on, depth-1/32 GET/SET,
   both atomic settings and the residual loop/inlining paths. Preserve each
   recipe's 4/8-core geometry, depth, connection count and values.
3. Run all eight `/home/user/Projects/calib/exec-merit.py` cells:
   `x{1s,2s}_a{0,1}_{unc,hot}`. Arms: headline→POST and headline→PAD-A;
   no ALT arm remains. Use 64 EXEC connections, pipeline 4, two children,
   16 generator threads, three ABBA blocks and 20 seconds per arm. 2s uses
   eight cores/6:2/16 shards; 1s uses eight fused cores/read-local 1/64 shards.
   Disable key/client balancing and auto-FLIP; select hot keys on different
   owners and retain the four plain INCR clients. Median completed EXEC/s is
   the harness verdict. Keep writer completions/share, unit INFO deltas and
   latency/progress alongside it. Label perf denominators separately per EXEC
   and per logical INCR (`2 × EXEC + plain INCR`). Repeat the four hot cells at
   8, 16 and 32 connections as the connection-count control.

For these recipes, server CPUs are 64–71 (64–67 for four-core recipes) and
load CPUs 72–95, with no load SMT, on a maintainer-scheduled quiet box. A
candidate effect should move POST while the behaviour twin remains flat;
PAD movement requires investigating placement before attributing the effect.
Rate/latency at matched offered load decides merit. No throughput claim is
made by this lane.

Forty-seven superseded trial build directories (5.46 GiB) were removed from
this worktree after their receipts were recorded. Final arms, production/unit
objects needed for freshness, command probes and gate artifacts remain;
`docs/wave6/build-pruning.json` lists the removed directories.

### Validation status

**All 200 selectable correctness/build-prerequisite jobs have passing complete-job
receipts on the final POST.** `tests/gates_test.py` passes all 71 tests, and the
complete `abba_selftest` job passes with the final wrong-selector negative controls
included. Its 768/785 EXPECT edits exist only in the throwaway selftest copy;
the integration worktree retains 739/756. The final audit has no pending jobs or
unresolved failures: `docs/wave6/correctness/summary-final.json`. This accounts for
204 available job names minus three performance jobs and the refused build-only
`tailgen_build` selection described below.

The final candidate's broad sweep completed **192 jobs / 767 passing rows /
zero failed rows**. Its R7, atomic units, every lane row, both persistence engines
and all four first-round txnorder cells pass. See
`docs/wave6/correctness/broad-final/receipt.json`. This is a partial-job ledger,
not a full gate or landing receipt. The earlier 169-job sweep had only the
R7 inventory and synthetic AOF fixture failures described above; both are
repaired and pass on the final candidate.

Both-engine standard-seed differential matrices are complete, and every one
of the four txnorder cells has three passing runs on the final POST (broad
sweep plus `txnorder-round-2` and `txnorder-round-3`). Complete legacy split/fused
jobs, final scheduler/ABBA selftests and the quiet timing-sensitive correctness
jobs also pass.
`docs/wave6/finish_jobs.py` invokes only complete gate jobs and records every
result. NETFIX_TLS_ORACLE remains unset; the gate uses its default TLS oracle.

Both complete differential matrices pass their four mode/atomic jobs and
mode-equivalence control (47 suite families per seed). Standard seeds are
`7 19 20 23 21` for io_uring and `7 19 20 23 22` for epoll. The differential
driver's existing armed-fused SORT skip is
retained because that particular suite requires split 6:2; the 20 declared skips
(five seeds × two atomic settings × two engines) are listed in each
`matrix-summary.json` and `docs/wave6/correctness/declared-skips.json`. The complete
gate SORT battery passes separately in both modes. A skipped differential leg is
not counted as a passing leg.

The first ABBA self-test copy lacked required fixture inputs; its gate helper
also ran with only two load CPUs and hit scheduler-fixture deadlines. A standalone
self-test first collided on a test port, then overlapped compilation and hit
fixture deadlines. These failed attempts are retained, not treated as passes.
The complete passing copy has every required input and 24 fixture load CPUs;
standalone `gates_test.py` ran serially on the allocation with port 26897.

The final persistence mode hooks exposed one more selftest integration issue:
`PersistfixWiring` copied the AOF job but omitted its new `txn_proof_boot`
dependency. It now copies the real selector, checks that each mode chooses the
right boot stub, and retains all stopped/reaped-slot and exact driver-argument
assertions in both engines. Two wrong-selector controls prove the fixture rejects
either wrong mode, including when Bash conditional execution disables errexit.
The full 71-test standalone suite and complete ABBA job pass with these controls;
see `gates-test-final-controls.{json,log}` and `abba-selftest-final-controls/`
under `docs/wave6/correctness`. Failed attempts remain separate from their
repaired receipts.

The complete fused release job exposed a second mode-hook assumption: its
historical `dispatched==executed (N)` row requested split-only fields that the
fused shutdown schema intentionally omits. Split keeps the exact old equality
assertion. The optional fused leg, tagged `fused=1` in the row context, instead
requires a nonzero unified count and an exact sum over valid, unique fused
thread rows. This is fused report consistency, not a claim that fused exposes
two independent dispatch/execute counters. Nine directed corruptions fail the
new check. The complete eight-row release job passes on rerun in both modes;
the old failed fused receipt remains. Other full fused legacy jobs pass,
including both debug atomic settings and all five ASAN rows. Quiet perfio and
atomic batteries also pass, with the atomic battery run in both modes.

**NOT RUN by design:** throughput/load-generator jobs `efficiency`,
`flip_saturated`, `atomic_floor`, the full `tests/gate.sh iteration`, the null
and landing measurements, and the full-gate-only tailgen load-generator row
(which has no selectable `GATE_ONLY_JOBS` job). They remain with the maintainer under the explicit
runtime authorization. The failed initial compile is retained in
`build/wave6/build-initial.log`; it is not a validation pass.

The source sweep traces 62 touched test files and 43 changed protocol literals
through script references, imports, declared unit objects and gate helpers,
including variable-selected dispatch batteries, linked netcmd/AT15/shutdown
checks, and the lazy-allocation shim. See `docs/wave6/coverage.json`. This is a
conservative source-reference map, not per-file execution instrumentation.
The entire runnable correctness-job inventory is selected independently of it.
Historical `execfix_unit.cc` has no Makefile target or gate job. The additional
standalone matches (including `doubles.py`, `replyschema.py` and historical lane
audit programs) are listed explicitly as **NOT RUN as standalone programs** in
`docs/wave6/standalone-sweep.json`. Matching gate consumers and standard
differential families run through the gate interface; no passing standalone
execution is inferred from them. The attempted `tailgen_build` selection
was explicitly refused by `GATE_ONLY_JOBS` (exit 2: build-only prerequisite,
select its consuming correctness job). Its only consumer is the full-gate-only
live load-generator row reserved to the maintainer. Thus the job is **NOT RUN**;
the `build/tailgen` target compiled and passed its final freshness check without
launching the generator.

The final read-only cleanup census found no owned workload processes or listeners
on ports 26800–26899 (`docs/wave6/correctness/cleanup-final.json`). No unrelated
process was stopped. Source, test, Makefile and integration-report whitespace
checks pass. Four inherited whitespace lines in the lanes' raw receipts remain
unchanged and are identified in `docs/wave6/correctness/source-review.json`.
