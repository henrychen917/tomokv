## readability-a6

Worktree/branch: `cx-readability-a6`, based on `9a09e5919092cc5e33aaf1e49e55994bdf8439b5`.
Frozen binary reference: `/home/user/Projects/bins/readability-pre-5c363128/tomokv`
(`5c3631281815c1652b3894d1736840c8466a5015`). No push or performance measurement is requested.

### Result and scope

The production executable is **IDENTICAL (11167504 bytes after stripping)** to the frozen
release. Changes are comments and nine local-variable bindings. Public names, class members,
types, macros, namespaces, template headers, include/definition order, executable tokens other
than those renames, and literal contents are unchanged.

All ten owned files have ownership/invariant headers. The sole additional production file is
`src/core/reorder.cc`: only its R7 generated block changed, through A2's formatter invoking
`tests/r7shadow_sync.py --write`. No generated text was edited manually. The token audit also
checks that this file is byte-identical to the lane base outside that block. All tool-marker
comments remain byte-identical at their original preprocessing-token boundaries.

Historical measurements and decisions are in
[docs/decisions/readability-a6.md](docs/decisions/readability-a6.md), with **19 dated entries**.
They are explicitly archived observations, not new throughput claims.

### Counts and coverage

“Rewritten passages” counts the history/diff-wording substitutions separately from file headers
and new/expanded contracts. Contracts include shorter ownership-bearing types/helpers and the
two shared-body contracts in `.inc` headers. Generated copies are excluded from these counts.

| Owned file | Rewritten passages | Contracts added/expanded | Phase landmarks | Header |
|---|---:|---:|---:|---:|
| `atomic_admission.h` | 1 | 1 | 0 | 1 |
| `atomic_parked.h` | 0 | 3 | 0 | 1 |
| `atomic_tripwire.h` | 6 | 4 | 0 | 1 |
| `ex_execute.inc` | 8 | 2 | 4 | 1 |
| `ex_loop.h` | 36 | 31 | 19 | 1 |
| `ex_txn_chain.inc` | 1 | 3 | 0 | 1 |
| `exec1s.h` | 1 | 4 | 0 | 1 |
| `exqueue.h` | 3 | 1 | 0 | 1 |
| `masked_queue.h` | 8 | 5 | 0 | 1 |
| `op.h` | 23 | 2 | 0 | 1 |
| **Total** | **87** | **56** | **23** | **10** |

All functions exceeding 50 non-comment code lines have contracts: `fused_pass_impl`, `run`,
`prepare_captured_local_mget`, `prepare_local_read`, `drain_local_reads_bounded_impl`,
`snapshot_control_pass`, `progress_snapshot_capture`, and `service_txn_boundary`. The shared
`ex_execute.inc` body has its own contract and four phases, plus contracts immediately above
its `execute` and `execute_timed` wrappers. Its latency specialization is identified in the
file header; the enclosing definition in another lane's TU was not edited. The three other
bodies exceeding 150 physical lines (`fused_pass_impl`, `run`, and
`drain_local_reads_bounded_impl`) carry four, five and four phase landmarks respectively.

Ownership contracts cover admission credits, parked indexes, diagnostic state, counter/bell
ownership, both queue implementations and their metadata, Op/Sink, local-read state/captures,
ExLoopT, and borrowed lifetime/notification scopes. Ordering arguments remain explicit at
Done publication, ready-mask fencing, QSBR rotation boundaries, the cutoff-before-floor read,
queue retirement, and ExDrain acknowledgements.

### Interface-first candidate disposition

**0 kept, 0 reverted, 0 compiled candidates.** This is an explicit scope/order limitation,
not a failed binary comparison. ExLoopT qualifies by size, but a full extraction is incompatible
with the simultaneous restrictions:

- `tools/source_anchors.json` pins `run`, `drain_tasks`, `drain_tasks_read_local_interleaved`,
  and the five named R7 generator inputs in `ex_loop.h`.
- `tools/lottery_build.py` reads the `refresh_live_config` seam by file path;
  `tests/wb_rule_checks.py` patches `drain_tasks` there. `tests/reorder_scope.py` also instruments
  the `execute` wrapper by path, regardless of whether that tool is in A1's live triage.
- Moving earlier unpinned definitions past those pinned definitions would violate the
  definition-order rule. The exact owned-file list provides no new topic-header destination;
  repurposing an existing fixed-point include would also alter include order.

No method was moved, no template header changed, and no unapproved header was added. A partial
suffix-only extraction into a newly assigned topic header could be considered under revised
ownership, but this lane does not claim to have evaluated its binary identity.

### Local rename table

Each row is scoped to one function body; no parameter, member or external identifier changed.
The machine-readable mapping is [renames.json](docs/readability-a6/renames.json).

| File / function | Old local | New local |
|---|---|---|
| `exqueue.h`: `push` | `t` | `tail` |
| `exqueue.h`: `push_prepared` | `t` | `tail` |
| `exqueue.h`: `push_batch` | `t` | `tail` |
| `exqueue.h`: `push_batch_prepared` | `t` | `tail` |
| `exqueue.h`: `pop` | `h` | `head` |
| `exqueue.h`: `newest_nonzero` | `h`, `t` | `head`, `tail` |
| `op.h`: `push_arg` | `ncap`, `n` | `new_capacity`, `new_argv` |

### Proposals for A19

These names are unchanged here. Each proposal needs coordinated callers, generated copies,
and source/ELF tool bindings where applicable.

| Current identifier | Proposed name | Reason / coordination |
|---|---|---|
| `ExLoopT` template parameter `Fused` | `FusedCapable` | True also supports split read-local runtime; coordinate every declaration/definition and generator. |
| `IofusedPrivateQueue` | `FixedFusedQueue` | Names lifetime-fixed lane addressing; coordinate template headers and source patch sites. |
| `fused_baseline_pass`, `fused_baseline_sweep` | `fused_owner_pass`, `fused_owner_sweep` | Name the active schedule instead of an experiment baseline; preserve/update R7 bindings and generator. |
| `r7_fused_*`, `r7_sweep`, `r7_drain_tasks*` | `reordered_fused_*`, `reordered_sweep`, `reordered_drain_tasks*` | Names scheduling behavior; requires cross-lane source/ELF updates. |
| `atomic_deferred_` | `dependency_parked_` | Includes transaction and script dependency waits, not only one atomic phase. |
| `xshard_retries_` | `ordered_continuations_` | Holds bounded continuations whose presence pauses fresh inbox work. |
| `multi_retry_layout_pad_` | `reserved_retry_tail_` | Names a layout reservation without referring to a removed fast-count representation. |

### Binary and source proof

Commands, with the maintainer's frozen INFO pins:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 96-127 make -j32 all
taskset -c 96-127 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

Output after the first storage/queue commit, after the complete source edits, and in the final check:

```text
IDENTICAL (11167504 bytes after stripping)
```

`docs/readability-a6/source-audit.py` uses `tools/source_tokens.py` to compare every edited
production file to frozen commit `5c36312818`. It reverses only the nine function-scoped
renames above, then requires equal raw preprocessing-token sequences and byte-identical
string/raw-string/character tokens. It separately checks exact tool-marker text and positions
against the A1/A2 lane base, and the generated-region boundary. **All 11 files pass.**

Every commit is formatted with `make format` / clang-format **18.1.8**, then checked with
`make format-check`. R7 check mode passes after the executor edits and after regeneration.
The source builds and `make -q all` pass. Full unit-target freshness and selected-job results
are recorded below.

### Selected gate validation

All invocations use `LC_ALL=C`, the frozen INFO pins above, CPUs **96–127**, and
TomoKV ports **25400–25498** (`GATE_TEST_PORT=25499` for scheduler fixtures). The gate
assigns eight server cores per ordinary correctness slot, **16 shards, ratio 6:2**; the
first selection uses server CPUs 96–119 and load CPUs 120–127 with no load SMT. No server
is started outside the selected gate jobs.

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
export GATE_PROOF_NO_RATES=1 GATE_TEST_PORT=25499
export GATE_ONLY_JOBS='source_identity reorder_sync reorder_identity perfex_units exbatch_units wb_rule_units wbland_units splitlocal_units reorder_engagement abba_selftest exbatch_live'
taskset -c 96-127 tests/gate.sh quick \
  --server-cores 96-119 --load-cores 120-127 --load-smt '' --ports 25400-25498
```

The first invocation (`build/gate-run.j3SbqL`) passes **20 rows, zero failures** across
12 counted jobs, plus its build-only dependency. The extra source-span classifier check uses
a single correctness slot with server CPUs 96–103 and load CPUs 104–127:

```sh
GATE_ONLY_JOBS='racefix_counters' taskset -c 96-127 tests/gate.sh quick \
  --server-cores 96-103 --load-cores 104-127 --load-smt '' --ports 25430-25498
```

The counter invocation (`build/gate-run.sDDdS2`) passes **1 row, zero failures**, plus
its build-only TSan prerequisite. Both **1s and 2s** complete with **zero TSan reports**,
normal child exit, and no listeners remaining. Across both selections: **21 passing rows,
zero failures**, 13 counted jobs and two build-only jobs.

All **61 primary targets** in `job_production_units`, its supplementary multi-DB arms,
blockfix cost witness/receipt and both blockfix2 targets have built. Together with `all`,
**67/67 `make -q` checks pass**, with commands and exits in
[make-freshness.json](docs/readability-a6/evidence/make-freshness.json). This verifies the
build-only helper's outputs independently of its exit status.

| Selected job | Passing rows |
|---|---:|
| `release` | 1 |
| `source_identity` | 1 |
| `reorder_sync` | 1 |
| `reorder_identity` | 1 |
| `reorder_engagement` | 1 |
| `perfex_units` | 2 |
| `exbatch_units` | 3 |
| `exbatch_live` | 2 |
| `wb_rule_units` | 4 |
| `wbland_units` | 2 |
| `splitlocal_units` | 1 |
| `abba_selftest` | 1 |
| `racefix_counters` (second selection) | 1 |
| **Total** | **21** |

Exact labels and verdicts are preserved in
[gate-runs.json](docs/readability-a6/evidence/gate-runs.json) and the copied ledgers/logs.
No counted row failed in either invocation. Copied `.log` files omit trailing horizontal
whitespace only; raw logs remain under `build/`, with both hashes in
[log-normalization.json](docs/readability-a6/evidence/log-normalization.json).

The relevant LIVE text matchers and their job coverage are listed in
[check-coverage.json](docs/readability-a6/evidence/check-coverage.json). `reorder_sync`
checks regenerated envelopes, the lexer/marker controls, and all **62 lottery insertion
sites**, including missing/duplicate-anchor rejection. `source_identity` covers **61 C++
translation units in both database variants and six shared C translation units**. R7 strict
identity verifies **352/352 bodies** and requires the missing-symbol/changed-opcode controls
to fail. The existing R7 PAD is **kind A, a behaviour twin: FIFO behaviour with the
candidate's text size/layout**; this is an identity control, not a measurement arm.

`tests/gates_test.py` runs inside `abba_selftest`: **83 tests, OK**. The label-fixture suite
has no standalone job in this gate interface; it was run directly without editing the gate:

```sh
LC_ALL=C taskset -c 96-127 python3 -m unittest discover -s tests -p gate_ledger_fixture.py
```

**12 tests, OK.** The gate's comparator self-tests use serverless fixtures; no ABBA
measurement is run. `GATE_PROOF_NO_RATES=1` excludes optional release-rate assertions,
without changing their normal defaults. These selections are partial checks, not a full-gate
certification. Existing frozen-reference-only patch branches (`lbplanner_pad`'s historical
source overlay and `rlfence_artifacts`'s archived CLI proof) were not replayed; they do not
read the edited current source in the active paths.

### Properties not established by the code

- **Compact read-cut age bound:** `Op::read_cut()` reconstructs the most recent congruent
  low-32-bit sequence. It does not enforce a maximum queue lifetime or saturate ancient cuts,
  contrary to the inherited comment. A stamp of 7 widened against `2^32 + 8` becomes
  `2^32 + 7`. The dispatch-to-execution bound needed to rule out that case is not established
  here. This is a potential read-ordering hazard if an operation spans a full sequence wrap;
  code remains unchanged for the binary-neutral lane.
- **Tripwire arming boundary:** clearing probes under the mutex, then storing the relaxed
  flag outside it, does not prevent an already-entered probe crossing arming sessions.
  Diagnostic data remains mutex-protected; the source no longer promises a strict session cut.
- **Parked-index exception rollback:** `AtomicParkedTasks::push_back` has multiple allocation
  steps without a rollback protocol. Its contract states that allocation exceptions propagate
  and does not claim a strong rollback guarantee.

No behavior fix or relaxation of a correctness invariant is included.

### Not run / unchanged gate accounting

The full iteration/full gate, throughput benchmarks, ABBA measurements, NIC rig and nightly
lottery campaign are not run. The selected `abba_selftest` job exercises serverless comparator
fixtures; it is not a measurement run. The source lottery checks run through `reorder_sync`;
no lottery witness binary or workload is launched.

No counted row was added, retired or moved across the quick-tier exit. `EXPECT_QUICK` and
`EXPECT_FULL` remain untouched; the required counts do not change. The label fixture is also
unchanged. No file larger than 1 MB is committed. Build products and scratch copies are not
committed. Completed R7 and executor-control scratch binaries/disassemblies were removed
(about **4.47 GB**), along with the local editing scripts. The peak observed worktree usage
was **28.04 GB**; after the TSan build and cleanup it is **25.55 GB**, below the 30 GB limit.
The report/evidence commit completes this lane. All lane changes are committed locally;
final Git cleanliness is verified after that commit. Nothing is pushed.
