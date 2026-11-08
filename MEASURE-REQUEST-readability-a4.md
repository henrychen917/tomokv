## readability-a4

Branch `cx-readability-a4`, lane baseline `9a09e59190`. Production reference:
`/home/user/Projects/bins/readability-pre-5c363128/tomokv` (maintainer-supplied;
never rebuilt). No push, throughput measurement or new PAD arm is requested.

### Result and scope

```text
IDENTICAL (11167504 bytes after stripping)
```

The production build matches the supplied frozen release. Source edits are
comments and scoped local-variable renames in the 12 assigned files. Includes,
definitions, public names, layout constants and all literal contents retain
their token order. No source file outside the lane is edited.

The documentation covers stop-aware boot barriers, release/acquire and QSBR
publication, queue debt across ownership boundaries, and issuer/coordinator
shutdown lifetimes. `main` has 11 boot/shutdown landmarks. The historical
rationale is preserved in 13 dated entries in
[docs/decisions/readability-a4.md](docs/decisions/readability-a4.md).

The header of `shutdown.cc` now distinguishes cancellation on the physical
issuer **before join** from coordinator reclamation **after join**. Contracts
also state existing limits: port probes do not reserve ports through activation,
boot waits have no total deadline here, diagnostic counters do not establish a
coherent cross-thread snapshot, and short/failed `getrandom` reads retain the
default hash material. These are documentation corrections, not behaviour changes.

### Counts and coverage

| Item | Count |
|---|---:|
| Existing handwritten comment groups rewritten or extended | 65 |
| Contracts added/completed | 42 |
| Handwritten phase landmarks | 29 |
| Owned files with top-of-file ownership/invariant headers | 12/12 |
| Local variable declarations renamed | 13 |
| Scoped rename mappings / changed identifier tokens | 12 / 71 |
| Interface-first splits attempted / kept / reverted | 0 / 0 / 0 |

Comment groups are consecutive comments at one preprocessing-token boundary;
counts exclude the generated envelope and include existing groups extended with
a contract or landmark. Three file headers move above the first includes, with
include tokens unchanged. The [coverage inventory](docs/readability-a4/coverage.md)
lists every contract and all 11 handwritten functions/lambdas exceeding 50 code
lines. All four handwritten bodies exceeding 150 physical lines have landmarks.
No handwritten class qualifies for the approximately 300-line member-body split;
the largest class is only 226 physical lines including fields and comments.

The protected R7 block is regenerated only by `tests/r7shadow_sync.py --write`
through `make format`. It receives the changed fused boot comments, six copied
landmarks and the worker contract. Other generated bodies remain the generator's
copies of mainline methods; they are outside the handwritten coverage counts.
No `TOMO_TOOL_FUNCTION`, `TOMO_TOOL_ANCHOR` or `TOMO_TOOL_BIND` comment changes
bytes or token boundary.

### Local rename table

| Function | Old → new | Declarations |
|---|---|---:|
| `append_reorder_info` | `multi` → `multi_client_runs`; `max_batch` → `largest_batch`; `s` → `thread_stats`; `row` → `row_buffer`; `n` → `row_length` | 5 |
| `append_read_local_thread_info` | `owned` → `shards_by_thread`; `row` → `row_buffer`; `name` → `role_name`; both scoped `n` locals → `row_length` | 5 |
| `print_shutdown_report_human` | `t` → `tenure_record` | 1 |
| `print_shutdown_report_json` | `t` → `tenure_record` | 1 |
| `main` | `buf` → `hash_material` | 1 |

[renames.json](docs/readability-a4/renames.json) records exact function scopes and
token occurrence counts. No parameter, member, type, macro, namespace or
externally visible function is renamed.

### A19 proposals — not applied

| Existing name | Proposed role name | Cross-file work required |
|---|---|---|
| `r7` namespace, `r7_*` members and `TOMO_R7_PATH` | `priority`, `priority_*`, `TOMO_PRIORITY_PATH` | IO/executor declarations, R7 generator substitutions, symbol controls and stable bindings; preserve marker identifiers |
| `FusedBootGate` | `WorkerBootGate` | Main, fused and split read-local boots plus fixtures; the type also coordinates ordinary split IO startup |
| `kGenthreadIfidBatchOps`, `kGenthreadExBatchOps` | `kLocalReadBatchOps`, `kOwnerTaskBatchOps` | Executor aliases/templates, tests and source-tool bindings; these distinguish read draining from owner-task batching |

### Binary, source and build proof

Executed with the supplied INFO metadata pins and CPU allocation:

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
taskset -c 32-63 make -j32 all
taskset -c 32-63 /home/user/Projects/calib/binary-neutral.sh \
  /home/user/Projects/bins/readability-pre-5c363128/tomokv build/tomokv
```

Output:

```text
IDENTICAL (11167504 bytes after stripping)
```

The [source proof driver](docs/readability-a4/prove_source.py) uses A1's raw
`tools/source_tokens.py` lexer. All **44,514 preprocessing tokens** equal both
lane base `9a09e59190` and frozen release source `5c36312818` after reversing only
the table's scoped renames. All **282 literal tokens** are independently
byte-identical, before splice normalization. Tool comments also remain at the
same token boundaries and match their lane-base bytes exactly. The driver
rejects changes outside the assigned source files and unaccounted comment moves.

`make format` and `make format-check` use the pinned clang-format **18.1.8**;
all **418** maintained files pass. Both source commits passed formatting before
commit, and the final documentation commit has the same formatting proof.
Every `job_production_units` target built successfully. The
[freshness sweep](docs/readability-a4/check_freshness.py) passes **68/68** checks:
`all`, all **61** primary unit targets, both recursive database witness builds,
the blockfix cost executable/digest and both blockfix2 units. The phony
`mdbqsbr-live-arms` recipe is checked through its two concrete recursive `all`
builds. [Target commands and results](docs/readability-a4/evidence/make-freshness.json).

### Selected gate and source-tool checks

The gate selection uses its own job interface, 8-server-core slots at ratio
6:2, 16 shards, CPUs 32–63 and ports 25200–25298. Its fixture port is 25299.
Every boot inherits `LC_ALL=C`. `GATE_PROOF_NO_RATES=1` is the existing partial
correctness opt-out; no full gate, ABBA measurement or NIC benchmark is selected.

```sh
export LC_ALL=C TOMO_INFO_GIT_SHA1=5c363128 TOMO_INFO_GIT_DIRTY=0
export GATE_PROOF_NO_RATES=1 GATE_TEST_PORT=25299
export GATE_ONLY_JOBS='source_identity reorder_sync reorder_identity reorder_engagement reorder_bounds wbland_units splitlocal_units lbplanner_units racefix_counters abba_selftest'
taskset -c 32-63 tests/gate.sh quick \
  --server-cores 32-55 --load-cores 56-63 --load-smt '' --ports 25200-25298
```

The relevant A1 LIVE text readers are covered as follows:

| Reader/check | Gate job |
|---|---|
| R7 generator and shared `reorder_sync` helpers, generator fixtures, source-token/anchor tests, lottery source preparation and its negative fixtures | `reorder_sync` |
| `reorder_noop`, `r7shadow_noop`, `r7shadow_pad` and instruction/symbol negative controls | `reorder_identity` |
| Reorder dispatch engagement and scan/lazy-construction bounds | `reorder_engagement`, `reorder_bounds` |
| `wbland_checks.py` reads ordinary and generated role bodies | `wbland_units` |
| `splitlocal_checks.py` reads `reorder.cc` and `genthread_pipeline.h` | `splitlocal_units` |
| `racefix.py` maps counter-write token spans in generated R7 bodies | `racefix_counters` |
| Source identity, assertion map and stable ids | `source_identity` |
| `tests/gates_test.py` and `gate_ledger_fixture.py` unittests | `abba_selftest` (fixture unittest through `gate_receipt.py --self-test`) |

An additional disposable-source run of A1's `prove_tools.py` passes **8/8
positive checks and 8/8 broken-anchor rejections**: `r7shadow_sync`,
`reorder_sync`, `r7shadow_sync_test`, `lottery`, `racefix_reports`, `lbplanner_pad`,
`wbland`, and `splitlocal`. The LB PAD source proof reads the owned boot files
from its frozen historical Git base, not from changed working-tree text; it
also passes. This supplements the selected gate jobs, without building or
booting a measurement arm.

Existing PADs referenced by these controls are **kind A behaviour twins**:
PRE policy behaviour with the candidate's text size/layout. No PAD layout
experiment is introduced. The legacy `tools/reorder_sync.py` command is also
executed in the disposable-source proof; it delegates to the same generator
exercised through the gate.

### Completion record

Selected gate: **13 passing rows, 0 failures**, across 11 counted jobs and two
build-only prerequisites. [Ledger](docs/readability-a4/evidence/gate.ledger),
[job exits](docs/readability-a4/evidence/gate-jobs.json),
[gate output](docs/readability-a4/evidence/gate.log).

- Source identity: **61 C++ TUs in both database variants, plus 6 shared C TUs**;
  stable assertion/source-identity controls **11/11**.
- R7 sync: current; stale-envelope and accounting controls pass; shared lexer
  controls **11/11**; all **62 lottery source insertion sites** and missing/duplicate
  seam controls pass.
- R7 FIFO identity: **352/352 ordinary bodies identical**, with required-symbol
  removal and opcode-mutation controls rejected. This is the existing candidate
  FIFO twin check; the separate frozen-release binary comparison above is also
  IDENTICAL.
- R7 engagement and lazy/scan bounds pass in both database runtimes; SplitLocal,
  writeback policy and load-balancer unit controls pass.
- TSan INFO/socket counter checks pass in both thread modes.
- `tests/gates_test.py`: **83 tests, OK**; `gate_ledger_fixture.py`: **12 tests, OK**,
  both executed inside `abba_selftest`. Its other serverless comparator/scheduler
  controls also pass; no ABBA measurements run.

Receipts are in [docs/readability-a4/evidence](docs/readability-a4/evidence).
Archived text logs trim trailing spaces; the gate's raw logs remain under
`build/gate-run.h9TnLk`.
The source-tool tree, FIFO twin/disassembly scratch and completed unit-job
scratch copies are deleted. Build prerequisites remain for review and reuse;
the worktree remains below **30 GB**. No committed file exceeds **1 MB**.

All required lane checks ran. Full iteration, throughput benchmarks, the nightly
lottery campaign and the maintainer's merge/push are **NOT RUN**. No counted gate
row is added or removed, so both quick/full expected counts and the quick-tier
boundary remain unchanged.
