## readability-a3

Branch `cx-readability-a3`, base `9a09e5919092cc5e33aaf1e49e55994bdf8439b5`.
No push. No throughput measurement is requested or claimed.

The production executable is identical to the maintainer's frozen release
`5c3631281815c1652b3894d1736840c8466a5015` after the prescribed stripping:

```text
IDENTICAL (11167504 bytes after stripping)
```

Both the initial phase-documentation commit and the complete source pass produced this
result. [Final binary output](docs/readability-a3/evidence/binary-final.log).

### Scope and counts

Only the six assigned source files were edited by hand. `src/core/reorder.cc` changed
only inside its generated envelope, through `tests/r7shadow_sync.py --write` invoked by
`make format`. No declaration, definition, include, layout, or executable token moved.

| Item | Count |
|---|---:|
| Pre-existing comment groups rewritten | 102 |
| Contract blocks added/replaced | 51 |
| Functions over 50 non-comment code lines covered | 23 |
| Phase landmarks | 31 |
| Owned files with ownership/inclusion/invariant headers | 6 |
| Local/parameter/internal-linkage renames | 0 |
| Interface-first splits attempted / kept / reverted | 0 / 0 / 0 |

Comment groups mean comments at the same preprocessing-token boundary, ignoring whitespace
and excluding tool markers; added contracts alone do not count as rewrites. Counts exclude
R7 copies. Contracts comprise four initial blocks (`IoLoop`, `init`, `run_loop`,
`parse_and_dispatch`) plus [47 further blocks](docs/readability-a3/evidence/contract-inventory.json).
The count excludes additional ownership detail incorporated into existing outbox/active-set
comments and the shared parser header. [Function coverage](docs/readability-a3/evidence/function-coverage.json)
counts all conditional branches and includes lambdas in their enclosing function; the shared
`.inc` fragment has its own header contract and four landmarks.

The required interface-first split is ineligible under the simultaneous path/order rules:
R7 inputs, source anchors, lottery and PAD sites are interleaved throughout `IoLoop`.
Moving only unprotected bodies after the class changes definition order relative to retained
bodies; moving all bodies violates their fixed source paths. The six-file partition also has
no new topic-header destination. No binary-changing candidate was retained or represented
as an IDENTICAL split.

[Decision log](docs/decisions/readability-a3.md) has 31 dated entries preserving removed measurements and
incident/implementation decisions as dated review entries citing their functions. Historical
figures are attributed to the removed source comments; they are not new measurements.
Contracts explicitly identify unhandled allocation failures and unestablished recovery where
appropriate. Read/write ordering, publication, buffer lifetime, migration, and reclamation
arguments remain at their source sites.

### Token, formatting, and binary proof

Run from this worktree:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 0-31 make format
taskset -c 0-31 make format-check
taskset -c 0-31 python3 tests/r7shadow_sync.py
taskset -c 0-31 python3 docs/readability-a3/verify_source.py
taskset -c 0-31 make -j32 all
taskset -c 0-31 make -q all
taskset -c 0-31 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

[Source proof](docs/readability-a3/evidence/source-final.json): all seven edited C++ files have
identical raw preprocessing-token sequences against both the lane base and frozen source.
String/character/raw-literal token bytes are identical. Tool-comment text and token boundaries
are exact against the lane base; the generator-only exception is checked outside its envelope.
Rename table: empty. [Format proof](docs/readability-a3/evidence/format-check.log): pinned
clang-format 18.1.8, all 418 manifest files pass. The frozen PRE executable was not rebuilt.

### A19 proposals (not applied)

| Current interface | Proposed name | Reason / coordination |
|---|---|---|
| `IoLoop::r7_run_loop`, other `r7_*` members | `run_reordered_loop`, consistently named reordered-role members | Name behavior; update R7 generator, bindings, ELF/source consumers together. |
| `IoLoop::r7_ReadLocalDemotionPlan` | `ReorderedReadLocalDemotionPlan` | Expose its relation to the ordinary planner without a historical lane number. |
| `IoLoop::PtrSet` | `ActiveClientSet` | Describe its borrowed client membership and indexed traversal. |
| `IoLoop::touched_`, `touched_list_`, `ntouched_` | `notify_owner_marked_`, `notify_owners_`, `notify_owner_count_` | Identify the folded owner-notification accumulator; source controls also name it. |
| `ReadLocalDemotionPlan::count_`, `nowners_` | `selected_read_count_`, `owner_count_` | Distinguish selected reads from destination credit demand. |
| `ClientMigration::catalog`, `routing` | `catalog_transfer`, `routing_transfer` | Identify the opaque owned migration payloads. |
| `IoLoop::flush_ifid_posts` | `flush_owner_notifications` | Name the actual action; callers and generated code need coordinated updates. |

### Gate/job proof

The checks use the gate's existing job interface, with the release INFO metadata and locale
pinned as above. The first selection is:

```sh
export GATE_ONLY_JOBS=source_identity,reorder_sync,reorder_identity,reorder_engagement,wb_rule_units,wbland_units,lbplanner_units,splitlocal_units,racefix_climon,auth,abba_selftest
export GATE_PROOF_NO_RATES=1 GATE_TEST_PORT=25199 GATE_DIFFER_ORACLE_CORES=24-31
taskset -c 0-31 tests/gate.sh quick \
  --server-cores 0-23 --server-smt '' --load-cores 24-31 --load-smt '' \
  --ports 25100-25198 --candidate-binary build/tomokv
```

The follow-up selection uses `GATE_ONLY_JOBS=abba_selftest,racefix_counters`,
`--server-cores 0-7 --load-cores 8-31`, and the same remaining flags and environment.
This gives one correctness slot, so the self-test and compilation run serially.
The gate adds build prerequisites itself. Its ordinary
correctness slots each use eight server cores, `--shards 16`, and ratio `6:2`; all assigned
cores and ports stay inside the lane allocation. `abba_selftest` exercises serverless
instrument fixtures, not a throughput measurement. Its receipt self-test runs the
`tests/gate_ledger_fixture.py` label-fixture unittest, and the same job invokes
`python3 tests/gates_test.py` directly.

Affected LIVE source-tool coverage from A1's triage table:

| Tool/check | Existing gate job or prerequisite |
|---|---|
| `tools/source_tokens.py`, source-anchor manifest, `tools/build_source_controls.py`, `tests/source_tokens_test.py` | `reorder_sync`; production-unit generation |
| `tests/r7shadow_sync.py`, `tests/r7shadow_sync_test.py`, shared `tools/reorder_sync.py` | `reorder_sync` |
| `tools/lottery_build.py`, `tests/lottery_build_test.py`: 62 insertion sites and missing/duplicate seams | `reorder_sync` |
| `tests/acl.py`: pub/sub source check | `auth` |
| Counter source check in `tests/racefix.py` | `racefix_counters` |
| `tests/wb_rule_checks.py`: policy/phase/stage/split-phase checks | `wb_rule_units` |
| `tests/wbland_checks.py`: clause/path checks and broken-source controls | `wbland_units` |
| `tests/splitlocal_checks.py`: forwarding/old-argument checks | `splitlocal_units` |
| `tools/lbplanner_controls.py`, `tools/lbplanner_pad.py`, `tools/lbosc3_pad.py` | `production_units`, `lbplanner_units` |
| `tests/reorder_noop.py`, `tests/r7shadow_noop.py`, `tests/r7shadow_pad.py` | `reorder_identity`, `reorder_engagement` |
| `tools/source_identity.py`, `tools/assert_map.py`, `tests/tomo_assert_checks.py` | `source_identity` |
| Gate scheduler, harness, and label-fixture unittests | `abba_selftest` |

The Climon runtime/control row also checks both modes. Existing PAD fixtures are kind A
**behaviour twins** (PRE behaviour with candidate text size/layout); this lane adds no PAD
arm or layout change. The full A1 matrix's branches reading other source files, archived
historical tools, full quick/full/iteration gates, throughput/ABBA campaigns, and NIC measurements are
**NOT RUN**. No gate row or expected count changes: `EXPECT_QUICK=1212` and
`EXPECT_FULL=1229` remain untouched.

The [first selection](docs/readability-a3/evidence/gate-first.json) completed with
**22 passing rows and one timeout**. [Completed check outputs](docs/readability-a3/evidence/selected-checks.log)
include the source and ELF controls. The timeout is
the `abba_selftest` row's unchanged 660-second deadline; all its completed unittest suites
passed, including 83 `gates_test.py` tests and 12 label-fixture controls. The timeout occurred
during the later `gateprod.py` self-test while the cold production-unit build ran in another
slot. This run remains recorded; the follow-up retries the whole self-test without concurrent
compilation. [Original timeout output](docs/readability-a3/evidence/harness-initial-timeout.log).
No assertion, budget, or expected count was relaxed.

`production_units` completed successfully, with all 65 readiness markers: the 61 primary
targets, the two-arm `mdbqsbr-live-arms` helper, the blockfix cost witness, and both blockfix2
witnesses. All **70** checks in the [freshness proof](docs/readability-a3/evidence/build-freshness.json)
pass. They check each
primary target, default `make -q`, `make -q all`, both live-arm `all` targets, and all four
supplemental output (including the cost witness's binary-hash receipt), and the TSan binary.

The [serial follow-up](docs/readability-a3/evidence/gate-followup.json) passed **2/2 rows**:
the complete `abba_selftest` and TSan counters in both modes. The same 660-second self-test
budget passed; [full unittest output](docs/readability-a3/evidence/harness-final.log) includes
83 passing `gates_test.py` tests and 12 passing label-fixture controls. The
[TSan output](docs/readability-a3/evidence/tsan-counters.log) records zero sanitizer reports,
clean exits, and no remaining listeners in both `1s` and `2s`.

The [latest execution of every selected job](docs/readability-a3/evidence/gate-latest.json)
therefore has **24 passing rows, zero failures**, across 13 counted jobs and two build-only
dependencies. This is a partial selection, not a full-gate certification. The original
timeout remains in the evidence and is not counted as a pass.

Completed disposable ELF twins and disassembly copies (1,036,942,075 bytes) were removed,
as were the comment-edit scratch scripts/manifests. Required build outputs remain available.
The worktree is below 30 GB, and no committed file in this lane exceeds 1 MB. No push,
merge, throughput measurement, gate-row change, or EXPECT edit was performed.
