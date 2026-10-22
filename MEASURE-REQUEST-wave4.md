# Wave 4 landing request

## wave4 integration

Lane wave4b resumes clean branch `cx-wave4` at `cd1423c97`. The four no-ff
merges are `2d276e45c` (compat2), `8bce7c3da` (moverfix), `4c692daf4`
(clockcut), and `7c054dbad` (notifyorder), on headline `8656f9fa9`.
`0350c7b33` retains the three clockcut labels. No push is requested.

This is **not an unqualified green acceptance report**. The declared lane rows
pass, but the sweep retains the pre-existing `cmdgap2` inventory contradiction,
eight standalone ACL-wake scheduler-fixture failures, and the previously
reported armed EXEC fan-out witness failure. The first epoll/armed differential
matrix also reports a duplicate TRACKING invalidation. None is waived or weakened.

The maintainer's compat2 EXPECT update and fixture sync remain intact.
DQ=DF=+16 (+3 compat2, +8 moverfix, +3 clockcut, +2 notifyorder), all collected
before the quick exit. Required landing counts are **685/702** from headline
669/686. Current constants remain **672/689**; this lane does not edit them.

The allocation is CPUs 64–111 and ports 26800–26899. All database servers use
that allocation. The initial differential launcher omitted the Python socket
fixture port fence, described below; its socket-reader control used an ephemeral
listener outside the assigned range. Performance benchmarks, measurement load
generators and the full iteration gate remain with the maintainer.

### Oracle and sweep

`docs/wave4/oracle/auth-redis74.json` identifies Redis 7.4.10 (`f103d127`) and
records pre-AUTH `XGROUP x` as `ERR unknown subcommand 'x'. Try XGROUP HELP.`.
`acl-redis74.json` records `NOPERM User alice has no permissions to run the
'acl|whoami' command`. The corresponding TomoKV auth and atomic-0/atomic-1 ACL
receipts agree. Thus the retained evidence covers all three corrected rows in
`cd1423c97`, not just one ACL mode. No further assertion change is assumed.

The whole-test-tree textual sweep retains 255 matching lines in
`docs/wave4/sweep-hits.json`. `sweep-job-map.json` maps 81 matching or touched
files to their owning jobs, standalone suites, or documented exclusions.
No additional assertion was changed during this integration.

### Merge composition and semantic checks

The earlier merge resolutions retain the four gate jobs and all their legs,
compose the R7 inventory additively, and preserve every lane's production
change. The Makefile's provisional additive budgets have now been replaced
where compile-only trials improve identity. `docs/wave4/row-inventory.json`
confirms **702 source labels = 702 fixture labels**, with multiplicities.
Collection lines are ntnew4 4124, moverfix 4184, compat2 4189, notify_order 4237,
and notify_aof 4238; the quick exit is line 4303. No label/count was dropped.

`docs/wave4/interactions.md` records the C2/R1/NT-new-7 composition, physical
versus logical expiry, raw-overwrite observation, mover carrier/claim routing,
clock pins, script retry/AOF routing, and the exact-deadline fixtures.
Plain SET in fused/read-local mode executes **none** of moverfix's five
PAD-patched sites; the enclosing dispatch kinds are element movers or LMPOP/ZMPOP.
This reachability result does not explain away the lane's measured SET result.

### Compile-only identity

All **29** pinned translation units were recompiled with IPA dumps. **102**
budget trials produce **85** distinct object-body sets; each distinct set was
linked and compared using the gate's strict instruction/address normalizer
against the five supplied binaries. No reference rebuild was needed.
`docs/wave4/budgets/{initial,scan,selected}.json` retain commands and selections.

| Unit | Provisional merge | Selected |
|---|---:|---:|
| src/persist/aof.o | 37179 | 37173 |
| db0/src/persist/aof.o | 37578 | 37572 |
| src/cmd/t_set.o | 23568 | 23582 |
| src/cmd/xshard.o | 129016 | 128705 |
| src/core/reorder.o | 147991 | 148006 |
| db0/src/core/genthread.o | 130407 | 130360 |
| db0/src/core/reorder.o | 149111 | 149000 |

Final linked inventory: **8,649 function groups**, **7,932 headline-identical**;
of **717 changed groups**, **604 equal a lane POST** and **113 remain different**.
All **12** directly named GET/SET/MGET/MSET-related groups equal headline (6)
or an intentional lane POST (6). The broader hot inventory is **489** groups:
394 headline-identical, 78 lane-identical, **17 residual**. Strict universal
identity is therefore **not achieved** and is not presented as a performance result.

The expanded command-path inventory includes prebuilt SET, string storage,
notification/TLS wrappers and generic MGET/MSET scatter handlers, not just the
12 directly named groups: **77 groups = 50 headline + 17 lane + 10 residual**.
Residuals are both `store_xstring_selected` copies, both armed
`cmd_set_prebuilt<true>` copies, four `cmd_xshard_only_impl` copies, and DB0
`xshard_execute` plus its cold fragment. They are included in the complete
changed-body table; `docs/wave4/identity/command-paths.json` makes this broader
command-path limitation explicit.

Every changed group is named with sizes, matching lanes and reason in
`docs/wave4/identity/changed-bodies.{json,md}`. The residuals include **73**
resolved-target/literal-only differences with identical instruction encodings,
**38** instruction-byte differences, and **2** symbol/clone emission changes;
strict diffs are retained in `residual-diffs.json.gz`. Composite changes and
unedited compiler propagation remain explicit merit inputs.

The gate's `reorder_identity` job passes the merged candidate, including all
negative controls: **293/293 = 146 normal + 147 DB0**. Missing policy symbols,
missing split-local parser and changed-opcode controls fail as required.
Receipt: `docs/wave4/proof/r7-final` (`build/gate-run.bzQ8Hu`).

### Build and correctness execution

`make -k -j32 all` plus every `job_production_units` file target (37), and
`mdbqsbr-live-arms`, completed successfully. **39/39 `make -q` freshness checks**
passed. Commands and individual statuses: `docs/wave4/production-build.json`.
The final post-proof audit repeats all 39 freshness checks, confirms the delivered
SHA is unchanged and that Makefile is the only production/test-tree diff since
`cd1423c97`, and finds no candidate process or listener in the allocated port
range. See `docs/wave4/final-build-audit.json` and the consolidated
`docs/wave4/proof-index.json` (which retains failed runs as failures).

The proof driver invokes the original `tests/gate.sh quick` with
`GATE_ONLY_JOBS`; its ledgers remain PARTIAL and cannot earn a full receipt.
The broad sweep uses server slots 64–71, 72–79 and 80–87; clients 89–109;
oracle CPU 88. Ports 26800–26879 belong to gate slots, 26880–26898 to ephemeral
serverless fixtures, and 26899 to the tree's configurable socket fixtures.
Build invocations use `-j32`. The adapter passes the battery's existing
`--no-rate-assertions` option to `atomic_ryow.py`, preserving all correctness
assertions. It also refuses any accidental `memtier_benchmark` launch.
No gate row, clock double, correctness deadline or assertion is changed.

The main selected-job run completed **576 rows, zero failures, 72 completed
jobs** (including build prerequisites). Its full ledger and archived text
receipts are in `docs/wave4/proof/merged-post`; original run directory:
`build/gate-run.lpGEqJ`. A second invocation of the same auth and notify jobs
boots the same POST in armed fused mode and passes **14/14** rows; receipts:
`docs/wave4/proof/fused-auth-notify`. These are explicitly PARTIAL gate runs,
not a landing or performance receipt.

| Lane | Gate rows | Required legs observed on merged POST |
|---|---:|---|
| compat2 | 3/3 | Each case runs 1s/2s × epoll/uring: 12 live cells. C1 has 1,522 oracle comparisons per cell; C2 includes its reservation unit; C3 includes two lifetime units and TLS 1.2/1.3 in every cell. |
| moverfix | 8/8 | 1s/2s × epoll/uring × databases 1/16, atomic 0; 56 unit family legs and 72 live legs including T05/G5. |
| clockcut | 3/3 | Unmodified `ntnew4_live` and existing clock double: 2s/uring, 1s/uring, 2s/epoll; 30 successful checks per row. |
| notifyorder | 2/2 | Ordering: 12 legs × 23 cases plus target/oracle NOLOOP checks. Script/AOF: all eight mode/engine/atomic legs, including reload. |

`docs/wave4/lane-leg-inventory.json` identifies every lane receipt. C1's
unchanged inventory explicitly excludes 24 variadic commands with no invalid
advertised arity and the local FLIP extension with no Redis counterpart;
these are not missing declared legs.

The main proof includes auth **7/7** (all three corrected rows), TLS **20/20**,
R7 identity and negative controls, `perfex_live` **2/2**, storage/core/atomic/
network/wait units, all four feature mode/atomic combinations, both fused
batteries, and all eight multidb combinations. The feature-battery rows for
keyspace notifications, hash-TTL, expiry, TRACKING, MULTI/EXEC, script,
blocking, AOF and ACL pass in both modes. The additional armed MVCC proof's
non-vacuity failure is recorded separately below. Snapshot and AOF jobs retain both engines and all their
declared mode/atomic legs. TLS receipts show real kTLS 1.2 engagement and the
TLS 1.3 userspace/key-update path; no TLS leg was silently skipped.

Supplemental invocations of the **same gate-owned** `debug-0`, `debug-1` and
`atomic_batteries` jobs complete in both fused postures:

| Fused posture | PASS | FAIL | Receipt |
|---|---:|---:|---|
| read-local 0 | 33 | 0 | `docs/wave4/proof/fused-mvcc-rl0` |
| read-local 1 | 31 | 2 | `docs/wave4/proof/fused-mvcc-rl1` |

Both failing rows are `execatomic` (the atomic-0 and atomic-1 starting boots).
The first invocation has one failing internal check: the atomic-0 deterministic
MGET arm records zero fan-out cuts. The second has three failing internal
checks: both deterministic MGET arms return some wholly new arrays instead of
the expected old snapshot, and the atomic-0 concurrent arm observes zero cuts.
The fixture labels those all-new deterministic responses `torn`; the concurrent
checks report zero mixed generations. These are failures, not passing evidence
of a pinned read cut. They reproduce the class of armed-witness limitation
already retained in `docs/moverfix/final-supplement` and its PRE controls.
No assertion, retry bound, tolerance or test ordering was changed. All other
rows, including atomic torn/window, RYOW, owner hazards and shutdown invariants,
pass in both fused postures.

Independent serverless suites pass: `gates_test.py` **67/67**,
`debug_load_test.py` **13/13**, `differ_test.py` **24/24**,
`infofields_test.py` **9/9**, and `loading_ready_test.py` **22/22**.
Receipts and commands are in `docs/wave4/serverless`.

The original `abba_selftest` job passes **1/1** row, including all 15 component
commands, in `docs/wave4/proof/abba-landing-complete`. Only the throwaway
copy has EXPECT 685/702; its label fixture already matched 702. The first
scratch attempt failed with six `FileNotFoundError` cases because the copy
omitted tracked documentation fixtures. That failed receipt is retained in
`proof/abba-landing`; adding the missing tracked files, with no assertion
changes, yields the complete passing run. `landing-sim-files.json.gz` records
the copied files and digests.

The standard split differential matrices pass on both engines: **475/475**
each, using permanent seeds 7, 19, 20, 23 plus rotating seed 21, both atomic
settings, and all four repeated MULTI/atomic-1/seed-19 legs. Each engine also
passes **16/16 mode-equivalence configurations**, with two boots per cell and
6,137 byte-identical replies per cell. The gate's older printed label says
"32 execution/knob combinations"; the retained result inventory makes clear
that this is 16 configurations and 32 boots. Receipts:
`docs/wave4/differ/{uring,epoll}-split` and `differ/split-summary.json`.

The first armed-fused matrices complete with **466 PASS / 0 FAIL** on uring and
**465 PASS / 1 FAIL** on epoll. The failure is `climon`, atomic 0, seed 19,
round 21 mode 1: TomoKV sends two `ck:10` invalidation frames; Redis sends one.
Its raw comparison is retained as
`docs/wave4/differ/epoll-armed-fused/climon-a0-s19-failure.txt`. Passing a later
run cannot erase this observed mismatch. TRACKING's source and the linked
invalidation/broadcast bodies are unchanged from headline, which does not by
itself establish the mismatch's cause or exclude a timing interaction.

The initial differential launcher called the fixture setup function but did not
use its returned environment. Thus `climon_reader_control` bound port 0 without
the port fence (the machine's ephemeral range is 32768–60999). Its short-lived
listener was outside the assigned range; the target and Redis listeners remained
on 26860–26863. This is a launcher error, not a test assertion change. The driver
now passes the fixture environment and records the bound ports. All four complete
standard matrices pass in four disjoint 12-CPU groups (eight server, one oracle,
three client CPUs) on ports 26860–26867. All **40** fixture listeners are recorded
on 26880–26883. Original receipts remain separate from this constrained replay.

| Constrained standard matrix | PASS | FAIL |
|---|---:|---:|
| uring split | 475 | 0 |
| epoll split | 475 | 0 |
| uring armed-fused | 466 | 0 |
| epoll armed-fused | 466 | 0 |

`docs/wave4/differ-constrained/summary.json` records the unchanged five standard
seeds, all four MULTI repeats per matrix, both armed non-vacuity witnesses per
engine, the 16-configuration/32-boot equivalence proofs, and all commands and
ports. The differential inventory observes 232 of 245 registered commands;
the 13 unobserved names remain explicit in each coverage receipt. This passing
replay does **not** clear the earlier duplicate invalidation.

Bounded fresh-state controls then run the unchanged `climon` seed 19 on epoll,
fused/read-local 1, atomic 0, databases 16: **3/3 headline and 3/3 POST** pass,
4,318 comparisons per invocation. Their six fixture listeners are fenced too.
Receipts and owned-server records: `docs/wave4/climon-controls`. The original
full-matrix mismatch is **UNRESOLVED**: these controls establish neither a fix
nor a headline reproduction. It remains an acceptance finding despite the
passing constrained full replay.

### Sweep findings outside the gate inventory

The unchanged standalone `dumpttl.py` cross-wire oracle battery passes all
eight mode/engine/atomic cells. `respresume_flip.py` passes all four split-mode
engine/atomic cells. These scripts have no gate job; they supplement, rather
than substitute for, the gate-owned rows.

The standalone `cmdgap2.py` battery **fails one of 41 checks in all eight
cells**: its architectural inventory check expects 245 commands and says
MOVE/SWAPDB are present, while its following forbidden-command assertion still
forbids MOVE/SWAPDB. The same unchanged test produces **byte-identical output
on the frozen headline binary in all eight cells**. The remaining 40 checks
pass in each cell. This is a pre-existing fixture contradiction, not a green
result; no assertion was changed. POST, headline, command and owned-server
receipts are under `docs/wave4/supplemental`.

Two additional serverless fixtures have no owning gate job. The unchanged
prebuild fixture passes all **four** mode/read-local combinations. The
unchanged ACL-wake fixture passes **88/96** cases; its eight admitted atomic-0
BLMOVE/BRPOPLPUSH cases fail at `stream scatter gather`, across both runtimes
and modes. This fixture directly drains owner tasks and requires every
`xshard_execute` call to return `Complete`. Moverfix intentionally returns
`Defer` when a destination precedes its source; the real executor queues that
result in `src/core/ex_loop.h:2516`, while this manual fixture has no deferred
queue. A print-only diagnostic preserves the original assertion and records
the actual result `Defer` before the same failure. This is an unadapted
standalone scheduler fixture, and remains **FAIL**, not waived. No assertion
or execution order was changed to make it pass. The gate-owned blocking,
ACL-wake and mover batteries pass with production dispatch. Build commands,
all 100 executions, and the diagnostic are in
`docs/wave4/serverless/extra-units`.

### Scope of existing findings

The moverfix lane's broader concurrent EXEC conservation counterexample failed
both headline and isolated POST. Its atomic-0 claim protocol does not establish
EXEC conservation; passing the standard MULTI/EXEC battery cannot erase that
reported counterexample. The inherited receipts are
`docs/moverfix/exec-final/runs.json` and `docs/moverfix/exec-controls`.
This integration does not silently broaden the claim.

### Maintainer measurement request

PRE is `/home/user/Projects/bench-bins/tomokv-headline-8656f9fa9`, SHA-256
`fa4d345732d4d7a0b051e9df9b1c9ae4f3a55411b651eeeeb8ee41c88b693cf0`.
POST is `/home/user/Projects/cx-wave4/build/tomokv`, SHA-256
`3dfe9e510917cc12e320e6e31ca9f22f8ac498c2e5353ce162ff273b2f01f8e5`.
The frozen lane POSTs supplied in the task remain the identity references;
this request adds no PAD arm.

Run the requested merged-versus-headline null/comparison with the gate's own
instrument on the quiet box, then the landing gate after applying the declared
count delta. The canonical iteration selection is the 18 cells in
`docs/wave4/measurement-cells.json`: t00, h01, h07, h11, h15, h17, h23, h27,
h31, h48, m47, m92, and t01–t06, with the gate's standard engine twins.
Keep the configured offered load, saturation/quiet controls, repeatability
rules and per-cell score (rate, latency or tail); retain cycles/op, IPC and
instructions/op alongside each PRE/POST result. The gate's verdict and the
maintainer's merit decision determine acceptance; instruction identity does
not substitute for that comparison. This lane makes **no throughput claim**.

### NOT RUN

| Item | Reason / retained limit |
|---|---|
| Performance/null comparison, load generators and full `tests/gate.sh iteration` | Explicitly reserved for the maintainer. The atomic-RYOW speed predicate is disabled through its existing correctness-only option; its overlap and ordering witnesses still run. |
| `tests/climon_128.py` | Requires a witnessed fused geometry with more than 64 IO owners; this lane is limited to 48 CPUs. The ordinary TRACKING and climon matrices run in both modes. |
| Broader concurrent EXEC conservation counterexample from moverfix | Its existing headline/isolated-POST failure is retained as a limitation; the integration runs the registered mover and MULTI/EXEC proofs, not a new counterexample campaign. |
| C1 invalid-advertised-arity comparison for its 25 enumerated exclusions | Twenty-four variadic commands expose no invalid advertised arity; FLIP has no Redis counterpart. The original C1 inventory records these exclusions explicitly. |
| Twenty fused differential SORT legs | The unchanged standard differential harness explicitly excludes SORT outside its required split 6:2 geometry. All corresponding split seeds run on both engines; no exclusion was added here. |

## wave4c

Started at `0d9950d7b` on `cx-wave4`. The maintainer's EXPECT values remain
**685 quick / 702 full**, and the committed label fixture is untouched. All
builds, diagnostics and correctness jobs use CPUs 64–111, builds use `-j32`, and
live listeners use ports 26800–26899. No push or performance run was made.

### Command-body result: exact restoration not achieved

The bounded search compiled **104 configurations / 102 distinct compiler
commands / 98 distinct object bodies** for both xshard and L4-prebuild units.
Every distinct candidate was linked and scored with the existing strict
normalizer against the full inventory, preserving a complete list of changed
and previously matching groups. **None restored any of the ten original
command-path residuals.** This is not proof that all possible compiler settings
have been exhausted. The full reference decisions, sampled values, GCC
inlining evidence and trade lists are in
[docs/wave4c/README.md](docs/wave4c/README.md) and
[docs/wave4c/selection.json](docs/wave4c/selection.json).

The retained unit budgets are xshard **128705 normal / 127713 DB0**, growth 0;
L4 prebuild retains GCC's defaults, **large-unit 10000 / growth 40** in both
namespaces. L4 growth-zero / budget-14000 twins also compile to the current
bodies. No compiler flag or production source change was selected.

Six command residuals (both `store_xstring_selected`, all four
`cmd_xshard_only_impl`) already have identical encodings after the existing
relocation masking; their strict mismatches name compiler-generated switch
tables and anonymous scalar data differently. A separate ELF-byte check proves
the disputed data bytes equal, but **does not waive or change the strict
identity result**. Both remain compared to headline. DB0 `xshard_execute` and
its cold fragment remain different from the required **moverfix** reference;
GCC rejects the mutex inline as an unlikely call whose code size would grow.

The two armed `cmd_set_prebuilt<true>` bodies combine intentional **clockcut**
deadline semantics and **compat2** expiry-notification semantics. Clockcut is
the semantic reference for the direct deadline edit, with compat2's guard
retained: neither frozen single-lane binary contains the combined behavior.
Relative to compat2, each current body differs only in seven deadline branch
opcodes. Choosing exact headline/moverfix, clockcut-only, or compat2-only SET
would discard an intended correctness change. The report keeps these as
residuals and does not weaken either fix.

The minimum hot residual count preserving every one of the **8,536 previous
reference matches** is unchanged. The unconstrained best trial, normal xshard
budget 129032, reduces historical hot residuals 17→16 and full residuals
113→108, but changes the already-matching DB0 `cmd_config`; it restores no
requested command body. Its complete seven-group trade is listed in the audit
and `selection.json`. It is rejected under the instruction to preserve prior
matches. No PAD arm is needed because the selected production ELF is unchanged.

### Rebuilt identity and SHA-256

All four relevant objects were forcibly rebuilt and merged POST relinked.
The full identity, residual-difference and expanded command-path inventories
were regenerated. Their contents equal the incoming inventories.

| Inventory (PRE = rebuilt POST) | Groups | Headline-identical | Lane-identical | Residual |
|---|---:|---:|---:|---:|
| Full function groups | 8649 | 7932 | 604 | 113 |
| Historical hot selector | 489 | 394 | 78 | 17 |
| Expanded command paths | 77 | 50 | 17 | 10 |

The two hot selectors overlap in 12 already-matching groups: their union is
554 groups with 27 residuals. The command residuals are separate from the
historical 17, not contained in that count. Fresh counts and regeneration
payload digests: [docs/wave4c/identity-summary.json](docs/wave4c/identity-summary.json).

Rebuilt POST `build/tomokv` SHA-256:
`3dfe9e510917cc12e320e6e31ca9f22f8ac498c2e5353ce162ff273b2f01f8e5`.
This equals the saved incoming `build/wave4c/tomokv-pre` byte-for-byte. The
reported `m8g_l0` MGET slowdown is **UNRESOLVED**. There is no new performance
arm or throughput claim; the retained measured regression is not cleared by
these compile-only checks.

### Harness change: ABBA row budget

The serial timing pass ran all 15 unchanged suite commands and their unittest
cases in **541.896 s**. Largest suites: abbagate 285.696 s, gate_receipt
130.491 s, gates_test 97.056 s, gate_history 21.487 s. The largest measured
individual cases were null-collection/comparison controls (114.051 s) and
completion-publication ordering (62.041 s).

The exhaustive dry-run argv case took **1.6768 s** for **64 cells × 2 arms**.
A separate profile confirms 128 `Runner.measure` calls and 320 layout loads,
plus fixed fingerprint work. Thus the iterative part scales with cells ×
arms, but it was not the dominant cost. No lane changed those cells or arms.
The failed landing spent 294.072 s in abbagate and 440.475 s in gates_test;
the test active at timeout was not evidence that it consumed the budget.

The existing `row_begin` special-case block now assigns this exact row
**1200 s**, with
`ROW_BASIS=abba-selftest-cx-compat2-851.44s-plus-40pct-rounded`.
The basis is the maintainer's completed **851.44 s** landing measurement:
851.44 × 1.40 = 1192.016, rounded up to a minute (40.94% actual margin).
The wiring control checks this value and basis for history, explicit-plan
and no-history inputs. **This is a harness change.** No test, assertion,
cell, arm, row or EXPECT value is removed or weakened. Per-suite and per-test
receipts: [docs/wave4c/timing/README.md](docs/wave4c/timing/README.md).

### Correctness and build receipts

The gate-owned ABBA row passes in **636.54 s**, with the explicit 1200 s
budget and basis visible in its receipt. All 15 suites complete. Its full
`gates_test.py` suite takes 186.826 s; `gateprod.py` takes 1.833 s.

All runs below use the tree's own `GATE_ONLY_JOBS` interface, including build
prerequisites, at 16 shards and the gate's eight-thread geometry. Fused debug
supplements use the existing `fused_candidate.py` boot wrapper; it changes
only mode/read-local arguments and executes this same POST. No assertion or
fixture was changed for a mode to pass. The ledgers are explicitly **partial**:
they do not certify the full EXPECT tally, performance tier or landing gate.

| Invocation | PASS | FAIL | Receipt |
|---|---:|---:|---|
| Main selected jobs | 198 | 0 | [wave4c-main](docs/wave4/proof/wave4c-main) |
| `atomic_units`, including MULTI/EXEC controls | 28 | 0 | [wave4c-atomic-units](docs/wave4/proof/wave4c-atomic-units) |
| `abba_selftest` | 1 | 0 | [wave4c-abba](docs/wave4/proof/wave4c-abba) |
| Fused debug, read-local 0 | 29 | 0 | [wave4c-fused-debug-rl0](docs/wave4/proof/wave4c-fused-debug-rl0) |
| Fused debug, read-local 1 | 27 | 2 | [wave4c-fused-debug-rl1](docs/wave4/proof/wave4c-fused-debug-rl1) |

The main selection contains `reorder_identity`, `compat2`, `moverfix`,
`ntnew4_live`, `notify_order`, `notify_aof`, both `feature-split` jobs, both
`feature-armed` jobs, both `fused` jobs, and both `debug` jobs. It covers:

- **R7:** 293/293 identical bodies, **146 normal + 147 DB0**, unchanged inventory.
  The missing-policy-symbol, missing-split-local-parser and changed-opcode
  controls all fail strict identity as required; normalizer self-checks pass.
- **compat2:** all three families × both modes × both engines, including all
  auth/arity comparisons, expiry controls, TLS 1.2 kTLS / TLS 1.3 fallback and
  both lifetime-unit modes.
- **moverfix:** all eight mode × engine × database-count legs, seven unit and
  seven live mover families plus live T05/G5 per leg; all 128 executions pass.
- **clockcut:** all three owned NT-new-4/NT-new-7 legs (split uring, fused
  uring, split epoll), including exact-deadline controls.
- **notifyorder:** 12 ordering legs × 23 cases, plus eight AOF/reload legs,
  with their Redis 7.4 oracle controls.
- **MULTI/EXEC:** both atomic settings in split, fused read-local 0 and fused
  read-local 1 feature batteries; ordinary MULTI/WATCH, EXEC isolation,
  reservation/order, `xmove`, and script checks run. Split debug and fused
  read-local-0 debug pass all rows. The armed EXEC failures below remain FAIL.
- **Serverless MULTI/EXEC:** the owning `atomic_units` job also passes: MULTI
  admin replies in both modes and namespaces; EXECABORT/WATCH armed, no-watch
  and no-error controls in all four combinations; and the missing-window
  `no-arm` controls, which fail as required in both namespaces. All other
  owned atomic-unit rows pass. Across the five gate invocations the ledgers
  contain **283 passing and 2 failing rows** (including repeated prerequisites).

**Unresolved armed fused EXEC findings:** the supplemental `execatomic` row
fails from both atomic starting boots, reproducing the class of witness
failure retained in the earlier wave-4 report. The first has one failed
internal check: atomic-0 deterministic MGET records zero fan-out cuts. The
second has two: that deterministic arm records zero cuts and one all-new
array instead of the expected old snapshot, and the atomic-0 concurrent arm
records zero cuts. The fixture labels the all-new deterministic response
`torn`; the concurrent checks report zero mixed generations. These observations
do not prove the required pinned cut and are not waived. No assertion, retry
bound, tolerance or ordering was changed. The other 26 debug rows pass in the
armed posture, plus its release-build row.

Standalone `python3 tests/gates_test.py` passes **67/67**, wall time **184.869 s**
(unittest reports 184.768 s), in
[wave4c-gates-test](docs/wave4/proof/wave4c-gates-test). `make -k -j32 all` and
all **37** exact `job_production_units` targets pass, as does the additional
MDB live-arm build. **39/39 `make -q` checks** pass both after the build and
at final verification. Exact commands, target names and statuses are in
[production-build.json](docs/wave4c/production-build.json) and
[final-freshness.json](docs/wave4c/final-freshness.json).

The machine-readable aggregate is
[correctness-summary.json](docs/wave4c/correctness-summary.json). Every completed
job's original text artifacts and digest manifest are archived beside its
command and partial ledger. The final resource check records no remaining
owned server and no TCP listener on ports 26800–26899. This lane adds **zero**
gate rows; EXPECT remains **685/702**, counted at the same quick-tier boundary.

### NOT RUN / remaining acceptance limits

- **Performance benchmarks, measurement load generators, and full
  `tests/gate.sh iteration`: NOT RUN**, reserved for the maintainer by the task.
- **Exact command-body restoration: NOT ACHIEVED** in the bounded compile
  search. The full/hot/command residual counts remain 113/17/10 and the
  previously measured MGET slowdown remains unresolved.
- **Armed fused EXEC witness: FAIL**, as recorded above. Passing selected
  correctness rows does not clear this finding or the retained findings from
  the earlier wave-4 integration report.
