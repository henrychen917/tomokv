# wave5 landing request

## wave5 integration

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. Worktree and branch:
`/home/user/Projects/cx-wave5`, `cx-wave5`. No push. Builds and correctness
server execution and final validation use CPUs 64–95 and listener ports
26800–26899. Integration and the authorized final correctness cohorts are
complete. Performance measurements and the full iteration remain reserved to
the maintainer; the exact seven unexecuted full-gate rows are recorded below.

All seven lane reports were read before their merges, including txnorder2b's
final additions and trackfix2's superseding design. The final reviewed WIP
states are preserved. Seven separate `--no-ff` merges retain this order:

| Lane | Frozen branch tip | DQ | DF |
| --- | --- | ---: | ---: |
| txnfix | 8dd5b8166 | 31 | 31 |
| bugs5 | 46221fd29 | 3 | 3 |
| compat3 | 751c3b586 | 6 | 6 |
| trackfix | ba03711ea | 2 | 2 |
| fliplisten | 4661b0c46 | 4 | 4 |
| netfix | c98b92959 | 5 | 5 |
| iofix | fcb52cd49 | 4 | 4 |
| Total | | 55 | 55 |

Required landing counts are **740 quick / 757 full**, from **685/702**.
Both protected assignments are unchanged. The independent label fixture was
composed from the seven lane inventories, including compat3's six declared
labels missing from its fixture. The merged source and fixture both contain
757 labels, and their multisets equal baseline plus every lane delta exactly.
No row is added by the directed integration subchecks.

Collector lines in the merged `tests/gate.sh`: iofix 4687–4690; netfix
4747–4751; bugs5 4785; compat3 4787; txnfix 4790, 4792–4793 and
4822–4825; trackfix 4841–4842; fliplisten 4847. All precede the quick
exit at line 4910. The 55/55 sum therefore has no quick/full discrepancy.
The independently derived collector inventory is `docs/wave5/row-inventory.json`.

### Merge resolutions and interaction review

- FUNCTION memory admission wraps txnorder2's script APPLY on the actual
  execution owner. The transaction's phase/preparation checks and admitted
  callback scope are both retained. The new EXEC subcheck exercises one-key admitted callbacks on both owners, including partial writes before a Lua error and cap restoration; validation is recorded below.
- The owner cron retains netfix's reclaim/purge calls and uses iofix's effective
  hz for both visit share and deadline. Empty-client passes still purge already
  reclaimed pages. The declared hz/reclaim runtime matrices are included in the final job sweep.
- FLIP listener state, transaction owner counters/retry lanes, and the hz/sleep
  coordinators all remain present in Server's cold tail. Locked layout assertions
  pass in the final production build.
- CONFIG duplicate-parameter detection retains the union of the network,
  encoding, hz and dynamic-hz rules.
- The initial additive inlining budgets were followed by 29 PRE/POST IPA trials,
  a neighborhood scan and linked-body selection. The generated audit retains
  every changed body and every residual hot group’s call sites against all eight
  references. Source attributes restore owner predecessor checks, WATCH predicates,
  FLIP pause checks, deferred retries and commit-flush call boundaries that shifted
  after composition. Final identity and counts are recorded below.

### Slowlog repair and directed control

The armed exact-operation path no longer calls `slowlog_capture` before execution.
A stack timing scope completes before Done (and before AOF owns completion); the
recorder checks the measured threshold before copying argv or retaining the immutable
client identity. Blocking and deferred scatter completion use the same scope.
The ordinary executor specialization contains no timing-scope test. Exact timing
has a separate cold helper so batch-average timing does not inherit its frame.

The directed core fixture forces elapsed time above the default 10ms threshold
without a workload or sleep, checks that the entry already exists at the Done hook,
then renames and removes the client directory entry. It covers disabled logging,
fast armed logging and threshold crossing in both modes. The negative control
publishes Done first; it must fail the before-Done assertion. Both controls are
part of the existing core lifetime row, so DQ/DF does not change.

### Interaction findings

* Writer episodes retain their owner-side ready/commit brackets before tracking
  certificates and Done. Tracking observation happens after predecessor parking;
  retrying fragments cannot certify an unexecuted read. Blocking serves retain
  their writer/WATCH brackets and notification execution scope. Async transaction
  notification batches are sealed only after joined publication at retirement.
  The tracking clock is global, so no new owner-local state can be stranded by migration.
* FLIP keeps retained listener descriptors in the server handover state. Client
  recv cancellation/reclaim and listener cancellation have separate tags. IO stops
  dispatch and cron during handover; DEBUG SLEEP polls through the worker membership
  scope on both IO and executor tenures and uses the registered wake path.
* TLS session cache state stays on the shared SSL context, not a listener owner.
  Handover retains that context; idle reclaim requires empty buffers and does not
  free pending TLS, send or ROB data. The existing listener and TLS matrices cover
  both successful and rollback handovers plus cipher/session behavior.
* Effective hz sets cron cadence and the per-pass client share. Reclaim’s idle age
  remains elapsed-time based; empty passes still purge previously reclaimed pages.
  Dynamic hz therefore changes visit frequency without changing the idle predicate.
* FUNCTION admission wraps script APPLY on its actual owner after txnorder2’s
  phase tests. The supported EXEC check dispatches independent one-key callbacks
  to both owners. A single cross-shard FCALL inside EXEC retains its existing
  CROSSSLOT limitation; the integration does not claim to add that command surface.

### First diagnostic attempts (retained, not passing evidence)

The first new-lane cohort found that the supplied Redis 7.4 binary has no TLS
support. Its TLS oracle legs failed loudly. An unmodified TLS build of the same
`f103d127` source was made inside `build/wave5/redis74-tls` with `BUILD_TLS=yes`;
TCP still uses the supplied binary. Oracle hashes and build provenance are retained.
That cohort also overlapped a relink: one boot saw a non-executable output and one
GDB listener-control boot saw changed addresses. Its `binary_stable=false` receipt
invalidates it as final evidence. Later cohorts use immutable SHA-named binary copies.
No failed leg is counted as a pass or removed from the final inventories.

### Directed integration defect: FUNCTION memory flags in EXEC

The new flags leg exposed `EXECABORT` under maxmemory even for admitted
`allow-oom` functions. EXEC cloned the declared write key before entering the
FCALL handler, so `atomic_admit` rejected the clone before FUNCTION's memory
scope could apply. The repair resolves the function/flags once and runs EXEC's
owner-version preparation inside that admission scope, before invoking the same
resolved callback. A second registry lookup is avoided so a concurrent library
update cannot change the flags between admission and invocation. A parked
preparation clears the Lua stack and restores the cap before retry.

The directed check uses callbacks on both owners, both uncapped and over-cap,
requires successful admitted writes and writes retained before a Lua error,
verifies subsequent reads within EXEC, rejects an ordinary non-admitted function
without changing its key, and checks that a following ordinary SET still sees
OOM. It remains a subcheck of compat3's flags row, with every original leg.

### R7 additive link inventory

The frozen headline has **146 normal / 147 db0** off-path physical bodies.
Six lane POSTs have the same inventory. FLIP listener handover's new translation
unit contributes exactly **six additional bodies in each namespace**: NoBorrow
parser clones (hot/cold at batch 0 and 32) and two owner-conflict closures.
The merged link has **152 / 153**, exactly the sum, with no other name/count delta.
The frozen fliplisten POST itself has 152/153 even though its branch retained the
older checker constants. `docs/wave5/r7-inventory/` contains all nine links' full
name/multiplicity inventories and the 12-entry merged delta.

The `wave5` checker inventory explicitly requires every added clone/closure and
retains all prior instruction/encoding comparisons. It does not mask or discard
any body. The FIFO behaviour twin compares all **305** physical bodies; the row
also requires missing policy, missing split-local parser, missing fliplisten clone,
and changed-opcode controls to fail. Legacy inventory selections remain available
for frozen historical binaries. This changes no public gate row count.
### Final build and instruction evidence

Production source is frozen at `b2e91a4ac` (later commits contain audit/report
artifacts). `make -j32 all` and all 42 `job_production_units` executable/stamp
targets plus both MDB parked/wake arms build successfully. All **45** `make -q`
checks pass: `all`, those 42 targets, and both underlying MDB build trees with
their exact macro flags. The phony MDB convenience target was built; freshness
is checked on its two actual outputs. Receipts: `docs/wave5/freshness.json` and
`docs/wave5/production-units-build-landing.json`.

The slowlog repair alone left the merged ordinary executor about ten instructions
per operation above the headline because the other lanes' guards and compiler
choices still compose there. Several field-caching trials were rejected. The
landed follow-up exposes the existing `xshard_task_should_defer` early return:
a non-scatter operation without `atomic_hazard` cannot defer in that helper.
Tagged MULTI and ownerless tasks were already handled earlier. Scatter debug
holds still enter the helper, and a WATCH-blocked plain writer marks its retry
before that retry parks. The directed core lifetime subcheck opens that exact
no-MVCC-record WATCH window, requires the retry to park before Done, releases
the claim, and requires one completion and RYOW in both modes. No layout or
ordering law changes.

Counts below are **whole bounded command-scope instructions**, not rates. Batch
32 values are totals for 32 commands. Default slowlog is 10,000 microseconds;
off is -1. The fixture uses the real production owner/scatter functions with
64-byte seeded values, no listener or worker loop. GDB counts all user-space
instructions, including library calls and NOPs. Only `clock_gettime` is replaced
with matching 1-microsecond ticks in both arms so debugger delay cannot create a
false slow command; its call site is counted, its substituted body is excluded.
The driver markers and validation after the scope are excluded.

Every counted production group matches the corresponding production link:
**79 PRE / 85 POST**, zero differences. All PRE groups also match the frozen
headline. The independently rebuilt PRE matches **all 8,641** frozen headline
groups. See `docs/wave5/instructions-landing/{runs,builds,provenance}.json`, the
per-cell PC traces, `command_scope.cc`, and `instructions.gdb.in`.

| Mode | Command | Batch | PRE default | POST default | PRE off | POST off |
|---|---|---:|---:|---:|---:|---:|
| 1s | GET | 1 | 1,684 | 1,387 | 1,007 | 977 |
| 1s | GET | 32 | 20,199 | 19,240 | 20,134 | 19,174 |
| 1s | SET | 1 | 1,889 | 1,520 | 1,143 | 1,111 |
| 1s | SET | 32 | 24,551 | 23,528 | 24,486 | 23,462 |
| 2s | GET | 1 | 2,309 | 1,997 | 1,632 | 1,602 |
| 2s | GET | 32 | 20,204 | 19,245 | 20,139 | 19,179 |
| 2s | SET | 1 | 2,514 | 2,129 | 1,768 | 1,736 |
| 2s | SET | 32 | 24,556 | 23,533 | 24,491 | 23,467 |

Every requested fast GET/SET cell executes fewer instructions than the headline.
This establishes the requested instruction condition; it establishes no IPC,
cycles/op, latency, or throughput improvement.

MGET has eight keys. Counts include prepare, owner execution/completion, and
retirement. Both modes have the same values below; all eight PRE/POST mode/atomic/
batch combinations ran independently. Batch eight is eight eight-key commands.

| Modes (independent, equal) | Atomic | Batch | PRE | POST | Delta/command |
|---|---:|---:|---:|---:|---:|
| 1s, 2s | 0 | 1 | 22,361 | 22,277 | -84 |
| 1s, 2s | 0 | 8 | 103,466 | 102,794 | -84 |
| 1s, 2s | 1 | 1 | 22,382 | 22,298 | -84 |
| 1s, 2s | 1 | 8 | 103,634 | 102,962 | -84 |

### Inlining and residual bodies

All 29 pinned translation units were re-derived with compile-only PRE/POST IPA
trials, derived-budget neighbors, and linked body scoring. The last round on the
frozen production source chooses the existing integration budgets unchanged:
`docs/wave5/budgets-landing/{initial,scan,selected}.json`. Earlier rounds selected
the committed Makefile values. Explicit source boundaries repair the predecessor,
WATCH, FLIP-pause, retry-service and commit-flush inlining changes. Ordinary
executor lambda ownership remains at `execute`, with a shared included body for
the separate exact-timed specialization.

**12/12 GET/SET/MGET/MSET hot groups equal the headline.** Across the full link,
7,133 groups are unchanged; 2,032 differ, of which 1,113 exactly match at least one
lane POST and 919 are residuals. The original 513-group hot set has 236 residuals.
A supplementary audit includes 42 scatter/notification/FUNCTION residuals,
including the `notify.inc` code emitted by `xshard.cc`. All eight references are
compared at each recorded call/jump site. Remaining changes include composed
lane semantics, the integration's timing and FUNCTION scopes, register allocation,
cold splitting, and cold standard-library inlining. They are not claimed identical
or faster; the maintainer's matched-load merit is the verdict.

Every changed body, source location, size, exact lane match or residual reason is
listed in [the full body inventory](docs/wave5/identity-landing/changed-bodies.md).
Call-site additions/removals and strict instruction diffs are under
`docs/wave5/callsites-landing/` and `docs/wave5/callsites-scatter/` (full
instruction diffs are gzip-compressed). Final instruction logs are also gzip;
superseded trial summaries and file hashes remain in `diagnostic-trials-*.json`,
with their raw archive kept only in `build/wave5/diagnostic-trials.tar.gz`. No normalizer
rule, source-line immediate, opcode, branch, member offset, register, or physical
clone count was suppressed to obtain these results.

### Additional integration checks and fixture repairs

The historical multidb boundary unit expected accepted descriptors to close at
FLIP stages. That contradicted fliplisten's approved final behavior. It now
retains all six database-stage admission windows and proves all **20 frozen
role-stage/entry combinations** retain the fd without Client allocation, then
admit it once when the admission epoch opens. Planning and stale Idle accepts
survive; repeated resume cannot duplicate admission; ordinary teardown closes
once. Both modes and both read-local states remain covered in the existing row.
The fixture explicitly reserves the real listener state before forcing FLIP
stages, as production does.

The gate self-test mock now executes the new slowlog completion negative control,
requires its exact failure/witness, and independently poisons both exit status
and witness. The standalone `python3 tests/gates_test.py` run passes **68 tests**.
No row count changes. One early standalone self-test invocation lacked the Python
port guard for its ephemeral socket-identity fixture; it is excluded from final
evidence. Final standalone and gate invocations use the bounded port guard.

The first broad diagnostic sweep had three failed rows: stale documentation
anchors (regenerated), the obsolete FLIP boundary assertion (repaired), and a
tracking schedule link overlapping the final production rebuild (not accepted as
runtime evidence). The final sweep starts only after all unit builds finish and
uses the immutable POST. The ABBA self-test's earlier scheduler-crash fixture
hit its existing deadline under overlapping work; its deadline/assertions are
unchanged. The final rerun has CPUs 80–95 exclusively; supplementary batteries
use 64–79 with their oracle on CPU 79.

### Arms and maintainer measurement request

- **PRE**: `/home/user/Projects/cx-wave5/build/tomokv-wave5-PRE`, SHA-256 `97ea4e0638863ac87b289290bd489d8ef93e5fc4808ad49bc71dfbd05a9c739e`.
- **POST**: `/home/user/Projects/cx-wave5/build/tomokv`, SHA-256 `201048f1b16aba87d73e2c13816f9b07b02afb9bef92d3ea40ca4eb46f61aca5`.
- **PAD-A**: `/home/user/Projects/cx-wave5/build/tomokv-wave5-PAD-A`, SHA-256 `9bbe8f2dc7b57c7016bc3e0ff6b8aacbf00e454352476377274a5ec45f3a2a6e`.

**PAD-A is kind (A), behaviour twin**: PRE behavior plus unreachable padding to
POST's total `.text` size, 8,076,601 bytes versus PRE's 7,747,526 (+329,075).
This controls total text size only; it does not reproduce each function's placement
or the candidate's cold data structures. The link uses the unchanged PRE objects.
The strict audit reports six address-annotation differences (jump tables and
unnamed linker thunks) plus the padding symbol; they are retained in
`docs/wave5/pad-body-diffs.txt`, not masked. No inverse-control PAD is claimed.

Maintainer: after applying the protected counts **740/757**, run the POST/POST
null and the landing `tests/gate.sh iteration` with the gate's normal instrument.
Compare the headline PRE, merged POST, and explicitly labelled PAD-A on the
headline GET/SET/MGET/MSET cells in both modes, including depth/batch 1 and 32,
atomic 0/1 where declared, default slowlog and disarmed slowlog. Retain the normal
full landing cell set; the extra slowlog arms isolate the targeted repair. Judge
matched-load rate/latency and per-cell cycles/op; instr/op and IPC explain the
result. PAD-A is a limited size control, not proof of cache-layout neutrality.
All throughput measurements, load generators for measurement, the null, and the
full iteration are **NOT RUN here**, as reserved to the maintainer. No push.

### Final correctness receipts

The frozen POST passes the broad **741-row** actual gate-job sweep. All **55**
new lane rows pass with every declared leg. Both `tests/differ_gate.sh` engine
runs pass split and fused+armed geometries, atomic 0/1, stable seeds 7/19/20/23
plus the gate-selected rotating seed, and all 32 mode-equivalence combinations.
The **40 climon seed legs** all pass; DIFF-TRK-1 is not filtered or skipped.

The final R7 gate row reports **305/305 identical physical bodies** and passes
all four missing-symbol/parser/clone/opcode controls. Bugs5 retains all 24 new
mode/engine/atomic legs and 24 legacy-control legs. Compat3 retains all 144
case/database/mode/read-local/engine/atomic legs, including the new EXEC memory
admission check in the flags cases. Both tracking rows retain 16 legs each;
FLIP listener handover retains all 16 direction/outcome/engine/atomic legs;
netfix retains the oracle plus every declared transport/mode/engine leg; iofix
retains all 16 feature/mode/engine legs. Writer R1–R12, the R8 handshake and R12
allocation/invariant/retirement controls, RENAME join, all 24 WATCH legs and both
inbox-wake modes pass. `docs/wave5/leg-inventory.json` independently requires
each declared log/result in the archived gate witnesses.

All eleven final cohorts return zero against the same immutable POST. They
contain **1,088 passing row observations across 175 jobs**; repeated modes and
engines are observations, not additions to the gate's declared count.

| Actual gate-job cohort | Passing rows |
|---|---:|
| Broad integration sweep | 741 |
| Differential, io_uring / epoll | 6 / 6 |
| Supplementary epoll batteries | 200 |
| Fused io_uring / epoll supplements | 72 / 40 |
| Bounded atomic + stream, io_uring | 7 |
| Bounded atomic epoll / fused io_uring / fused epoll | 5 / 5 / 5 |
| Quiet ABBA self-test | 1 |

The quiet ABBA row passes in 893 seconds with its unchanged assertions and
budgets. Its throwaway worktree differs only in the protected counts, 740/757;
the 757-label fixture is byte-identical to the integrated fixture. The copy is
removed after archiving the receipt and exact diff. The standalone gate
self-tests pass 68 tests, and the touched INFO differential self-test additionally
passes all 10 tests. All 45 freshness checks pass again after gate cleanup.

[Final receipt inventory](docs/wave5/final-correctness.json) records commands,
binary bindings, cohorts and remaining full-gate labels. There are 748 literal
fixture entries covered; two differential aggregate entries are represented by
their complete atomic-part jobs on both engines, leaving the seven explicit
NOT RUN entries below. No incomplete or aborted run is accepted as passing
evidence. Full per-leg text/JSON logs, server logs, file hashes and ledgers are
retained in each cohort's `witnesses.tar.gz`, `manifest.json` and `rows.json`.
Temporary gate data and obsolete compile trials were removed; the final build,
required production units, PRE/POST/PAD arms and instruction harnesses remain.

`docs/wave5/coverage.json` traces 79 touched test files, their helper imports,
variable-driven battery lists, linked units and matching gate jobs. It also
records 28 changed reply/error/INFO strings with matching tests (include-file
names are excluded from this protocol sweep). The selected correctness
consumer jobs form a superset of all runnable matching jobs. The explicit
semantic review covers EXEC/WATCH ordering and counters; tracking invalidation
ordering/accounting; HSCAN and slowlog identity; stream/pubsub/FUNCTION grammar,
error precedence and memory flags; CONFIG network/TLS grammar and query/buffer
INFO fields; hz/dynamic-hz, DEBUG SLEEP and shutdown behavior.

**NOT RUN:** the historical standalone `tests/txnfix_audit/*` scripts and
`tests/watchlive_gate.sh` have no `tests/gate.sh` job; their directed EXEC/WATCH,
writer-episode, mover and differential successor rows run in the final sweep.
`tests/doubles.py` is a standalone legacy match for a shared float-error string,
also with no gate job; the matching registered command/feature/differential
batteries run. No new gate row or substitute driver was invented for these
historical scripts. `atomic_floor` and `efficiency` remain **NOT RUN** because their job bodies
run throughput/wall-time/scaling measurements reserved to the maintainer. This
also leaves their bundled tripwire round-trip and 400-roll pipe-order rows
unexecuted here; they have no separate partial-job entry. Their three efficiency
rows and three atomic-floor rows are named in the final receipt. The standalone
coordinator row `tailgen client-lb outstanding bound` is also **NOT RUN**: it is
outside the partial-job interface and invokes the full placement/open-loop
instrument. The maintainer’s full landing gate owns it. Throughput load generators,
the null and full iteration remain **NOT RUN**. The partial differential interface
emits atomic-part labels; both full-matrix aggregate labels are represented by
their passing atomic 0/1 parts on both engines, not invented ledger rows.

One supplementary cohort was stopped as the orchestration changed to give ABBA
an exclusive CPU allocation. Its partial/failed ledger is archived as
`supplement-epoll-aborted`; the complete cohort restarted from fresh state.
Earlier diagnostic failures and the non-TLS supplied oracle are documented above;
all archived attempt receipts remain distinguishable from final passing runs.

## wave5b

Base `fc138d82e`, branch/worktree `cx-wave5`, no push. Correctness and builds
use only CPUs 64–111 and ports 26800–26899; builds use `-j32`.

**Disposition: authorized fallback. WB4.1 is reopened.** The production change
reverts the deferred-work predicate from `593e7215e`, restoring the headline's
`src/core/wb_rule.h` byte for byte. The bounded-completion/bytes/half writeback
rule, latency policy, load detector and all other iofix fixes are unchanged.
`1582c3559` is retained: its extraction follows IO4.9's cron-bounded `wait_ms`,
which remains present and does not depend on WB4.1's work predicate.

The fixed-count driver is `tests/wave5b_client.cc`: 64 connections, eight keys,
depth 8, 2,048 requests per connection (131,072 total per run), 64-byte values,
independent connection keysets, exact RESP replies, no clock or rate output.
READY/GO and DONE/STOP barriers exclude population and disconnects from the
counter interval. `tools/wave5b_trace.py` inserts counters only in disposable
source copies: actual IO wait/resume sites, received wake messages, pending
FIFO visits, deferrals, send submissions and completion notifications. Counts
are single-writer relaxed loads/stores in separate per-IO cache lines. Total
park counts include brief empty-FIFO startup/tail waits; pending-FIFO parks
identify the disputed mechanism directly. Trace instrumentation can affect
scheduling; these are mechanism counts, not throughput evidence.

Three repeats of each requested shape ran on headline PRE, integrated POST,
and integrated POST with only WB4.1 reverted. PRE and POST-REVERT always had
zero pending-FIFO parks; integrated POST had them in every shape. MGET also
showed fewer FIFO visits and more wake messages. MSET showed many more wakes
and fewer sends, consistent with its measured batching change. This confirms
WB4.1 changes the park mechanism, but does not establish the numerical cause
of the maintainer's throughput deltas: this directed MGET shape did not
reproduce the measured send-count penalty. Full totals, per-request counts,
individual repeats, source overlays and hashes are under `docs/wave5b/`;
`mechanism-table.md` and `mechanism-summary.json` summarize accepted cohorts.

A completion-derived grace window was implemented and tested, then removed.
It used the existing pass clock, twice the largest observed busy-tenure
completion interval, and excluded intervals spanning a park. It passed the
WB4.1 idle-CPU job through the gate in all four mode/engine legs (receipt
`docs/wave5b/gate/adaptive-idle/result.json`). Its quiet mechanism repeats still
had pending-FIFO parks: MGET atomic 1 = 1/0/4, MGET atomic 0 = 2/1/3, MSET atomic
1 = 135/81/32, versus zero on PRE and POST-REVERT. It therefore fails the
requested PRE-equal park behavior and is not shipped. One earlier adaptive
cohort overlapped a compile; it is explicitly INVALID and excluded in favor
of the complete `adaptive-quiet` rerun. The attempted source is retained in
commit `762c3d5bc`, not in the final production tree.

WB4.1's collector at base line 4687 preceded quick exit line 4910. Removing it
is **DQ=-1 / DF=-1; required totals 739 / 756**. Current quick exit is line
4904. The label fixture loses exactly that label; its multiset equals source
inventory. `EXPECT_QUICK=685` and `EXPECT_FULL=702` are untouched. The parked
CPU battery remains available as an explicit reproducer of the reopened
issue. Existing FIFO/R7 progress witnesses and their mutant now assert that
both bounded and saturated deferrals report work. No other gate row is removed.

### Frozen arms and identity

| Arm | Path | SHA-256 | .text bytes |
|---|---|---|---:|
| Headline PRE | `build/tomokv-wave5-PRE` | `97ea4e0638863ac87b289290bd489d8ef93e5fc4808ad49bc71dfbd05a9c739e` | 7,747,526 |
| Wave-5 POST baseline | `build/tomokv-wave5b-BASE` | `201048f1b16aba87d73e2c13816f9b07b02afb9bef92d3ea40ca4eb46f61aca5` | 8,076,601 |
| Final fallback POST | `build/tomokv` | `2028fd77cd548e99de672fe058c164b665a248464996518773b56dd9207d12dc` | 8,073,113 |
| POST-REVERT | `build/tomokv-wave5b-POST-REVERT` | `2028fd77cd548e99de672fe058c164b665a248464996518773b56dd9207d12dc` | 8,073,113 |
| PAD-A | `build/tomokv-wave5b-PAD-A` | `6e81f38fa1ec61e6904231c8e121a546c9febca56d3bee8bf55abd0928907fae` | 8,073,113 |
| PAD-B | `build/tomokv-wave5b-PAD-B` | `b0c5b3ef96e1fd37bf5990c67e4c3693d76ca7bf80321881f86dc6cb60d7180a` | 8,076,601 |

Final POST and POST-REVERT are identical because the authorized fallback was
selected. PAD-A is **kind A, behavior twin**: integrated wave-5 POST behavior,
including WB4.1 parking, at final POST's exact `.text` size. A shrinking
candidate cannot be matched by simply padding the original. This control
rebuilds the identical baseline source with `-falign-functions=1`, then adds
40,352 unreachable bytes. It controls total text size, **not per-function
placement**. The normal baseline rebuild matches every linked normalized body
of the frozen wave-5 POST; its ELF SHA differs because its build directory
changed. The alignment flag and complete link command are in
`docs/wave5b/pad-a.json` and its reproducible builder.

PAD-B is **kind B, inverse control**: final fallback behavior plus 3,488
unreachable bytes restoring wave-5 POST's text size. Every original candidate
function address and size is preserved. Both controls preserve GNU properties;
debug sections are stripped from these two controls to keep storage small.
Neither padding function is called.

**12/12 GET/SET/MGET/MSET hot groups match both the headline and wave-5 POST.**
The strict gate linked-body normalizer reports 114 changed groups against
wave-5 POST; each is listed with its reason in
`docs/wave5b/identity/wave5-post-changed-bodies.{json,md}`. Source edits are
confined to the work predicate; remaining differences are recorded compiler
propagation, not ignored. The object-level ccfix audit reports 122 changed
emitted bodies and 1,213/1,213 command-handler bodies equal. Every object delta
has a reason in `docs/wave5b/objects/changed-bodies-with-reasons.json`.
The ccfix and lbstall strict hot-body checks return nonzero for the intentional
writeback changes; they are not represented as whole-server identity passes.
Merit, not those strict exit codes, decides acceptance.

### Completed correctness proof

The final correctness batteries used `tests/gate.sh`'s selected-job interface
with frozen ELFs; these are partial-job receipts, not a full-iteration receipt. The joined
receipt is `docs/wave5b/proof.json`, with per-cohort logs, row inventories,
launch records and compressed witness archives under `docs/wave5b/gate/`.

| Check | Result |
|---|---|
| Writeback jobs | `wb_rule_units`, `wbland_units`, and `wb_policy` passed; live policies 0/1 covered both modes and both engines |
| Remaining iofix rows | IO4.9, IO4.10 and IO4.17 passed all 12 mode/engine legs |
| FLIP and DEBUG SLEEP | Requested unit/live rows passed; listener conservation passed all 16 engine/atomic/direction/outcome legs; DEBUG SLEEP covered both modes and engines |
| Standard differential suites | 1,880 passing checks across uring and epoll: 1,860 suite legs plus 20 MULTI/armed-fire checks, no failed checks |
| Mode equivalence | All 16 current cells per engine passed (32 total); inventory derived from `tests/mode_equivalence.py` |
| `python3 tests/gates_test.py` | 68/68 passed with unchanged assertions and deadlines |
| Build and freshness | `make -j32 all`, all 42 `job_production_units` targets, and both MDB live arms built; all 45 `make -q` queries passed |
| PAD controls | Both PAD-A and PAD-B passed the live writeback job in both modes and engines |
| Gate inventory | Source and fixture label multisets match; required quick/full counts are 739/756 |

The differential plan retained standard permanent seeds 7, 19, 20 and 23.
Its rotating seeds were 21 for uring, 22 for epoll atomic 0 and 24 for epoll
atomic 1. The oracle was `/home/user/Projects/redis74/src/redis-server`.
The final six correctness cohorts contain 168 passing row observations;
repeated observations are not additional gate rows. `reorder_sync`, the
network-command and split-local unit jobs also passed in the final sweep.

Two harness failures are retained rather than counted as passes. The first
FLIP-listener run gave GDB the engine/mode adapter script instead of an ELF;
its four rows failed before server startup. Rerunning the same frozen ELF
directly passed all 16 legs and all four rows. The wrapper now rejects that
combination. The first `gates_test.py` attempt had four scheduler-fixture
timeouts while compiles ran; the complete quiet rerun passed 68/68 without
changing deadlines. Strict label-fixture checking still reports the protected,
stale `EXPECT_FULL=702`; there are no missing or extra fixture labels. The
maintainer must set the required totals to 739/756. Neither EXPECT constant
was edited by this lane.

**NOT RUN:** performance benchmarks, ABBA, PMU measurements and the full
`tests/gate.sh iteration`, reserved to the maintainer. Fused SORT differential
legs are excluded by the standard split-only suite plan; fused FLIP is not
a supported feature. The FLIP saturation load was used solely for its
correctness assertions; its rate output supplies no performance claim.

Final arm hashes were rechecked after verification. Launch evidence records
CPU affinities within 64–111 and listener ports within 26800–26899. Duplicate
temporary object trees totaling 4.7 GB were removed; deliverable and trace
ELFs, production dependencies and indexed evidence remain. No other lane's
artifacts were removed.

### Maintainer measurement request — NOT RUN

`docs/wave5b/merit-cells.txt` parses as 24 cells: exactly `mk2g_a1_p8` and
`mk2s_a1_p8`, the 14 generic writeback cells, and eight 2s GET/SET controls
(depth 1/32 × read-local 0/1). Primary acceptance compares **final POST against
the headline PRE** with the gate's own ABBA instrument, its reviewed placement
and matched nulls. No full `tests/gate.sh iteration`, performance benchmark,
rate measurement or PMU performance pass was run by this lane.

```bash
common=(--build-reference 0 --cells docs/wave5b/merit-cells.txt --subset full
        --server-cores "$WAVE5B_MERIT_SERVER" --load-cores "$WAVE5B_MERIT_LOAD"
        --ports 26800-26899)
taskset -c 64-111 python3 tests/abbagate.py "${common[@]}" \
  --reference-binary build/tomokv-wave5-PRE --candidate-binary build/tomokv \
  --output build/wave5b-merit-headline
# Attribute behavior versus text-size effects against integrated wave-5 POST:
for arm in tomokv tomokv-wave5b-PAD-A tomokv-wave5b-PAD-B; do
  taskset -c 64-111 python3 tests/abbagate.py "${common[@]}" \
    --reference-binary build/tomokv-wave5b-BASE --candidate-binary "build/$arm" \
    --output "build/wave5b-merit-$arm"
done
```

Deciding number: rate at matched offered load, using the instrument's unchanged
null/acceptance rules. The MGET deficit must disappear against the headline,
with no material regression in MSET or the control cells. Record commands per
send alongside rate, and depth-1 p50/p99. A separate diagnostic PMU pass should
report cycles/op, instructions/op and IPC; instructions alone are not merit.
PAD-A should stay with integrated wave-5 POST if the change is behavioral;
PAD-B should track the fallback if its gain survives restored text size.
Alignment/placement remains a limitation of PAD-A, hence the inverse control.
Preserve exact hashes, geometry, order and null receipts; identical-arm spread
above 2% requires diagnosis. This lane makes no throughput claim.


## wave5c

Correctness repair of the wave5b landing failures, based on `979c96861`. No
performance claim. All commands in this lane used CPUs 64–111; parallel zc
slots used separate 8-core servers (6 IO + 2 EX, 16 shards), 8 load cores,
and ports 27000–27029. Other correctness work uses 26800–26899. Original
landing evidence is preserved under [docs/wave5c/landing](docs/wave5c/landing).

The netfix jobs now explicitly pass `--tls-oracle`, using
`GATE_TLS_ORACLE_BIN` or `${REDIS74_TLS_ROOT}/src/redis-server`, with
`REDIS74_TLS_ROOT=/home/user/Projects/redis74-tls` by default. The four TLS
consumers validate the executable and perform a TLS PING against it; there
is no fallback to the TCP oracle. An oracle failure stops dependent legs
instead of cascading through absent result files. The Unix-only job receives
the same explicit argument. The complete consumer search and canonical build
provenance are [recorded](docs/wave5c/tls-consumers.txt). Missing-path and
non-TLS-oracle negative gate runs both failed and named the offending path;
see `docs/wave5c/tls-{missing,unsupported}-proof.log`.

The reproduced leak was a closing Client removed from `ThreadCtx::clients()`
by `close_client()` before its executor epoch had quiesced. It remained in
`active_` for a retry. When the epoch ended and shutdown won before another
IO pass, the final two `reap_dead()` calls could not find it. The diagnostic
iofix run captured two such clients with empty ROBs and **no recv, send, or
serve pin**, while the live-list shutdown report saw zero connections. This
reproduction requires neither NT4.19 receive cancellation nor retained FLIP
accepts. The existing ownership gap is exposed by the faster iofix signal
exit; the baseline experiment does not establish it on headline.

| Matched release / source ASAN arm | Gate zc runs | LeakSanitizer failures |
|---|---:|---:|
| wave5b `2028fd77` | 30 | 0 |
| headline `a7dfb9d23` | 30 | 0 |
| iofix `a7a3d72a` | 30 | 6 |
| fliplisten `191a4d96` | 30 | 0 |
| netfix `9cfcbcb1` | 30 | 0 |

Each historical release was paired with an ASAN build of its own source,
not with the current tree's ASAN binary. The partial-job-only
`GATE_ASAN_BINARY` override checks executable ASAN identity and leaves the
normal gate build path intact. Source refs, flags and hashes are in
[baseline-builds.json](docs/wave5c/baseline-builds.json); all 150 outcomes and
raw leak paths are in [baseline-zc.json](docs/wave5c/baseline-zc.json).
The extra instrumented reproduction is
[iofix-observed-close-pins.log](docs/wave5c/landing/iofix-observed-close-pins.log).

The fix is implemented in `src/core/shutdown.cc`. A physical-worker lifetime
guard synchronously cancels network operations on the original io_uring
issuer, after its persistence lifetime guards drain. It runs at physical
thread exit, including former IO owners after FLIP, not at a role change.
After all workers join, IoLoop destruction collects and deduplicates clients
from live, active, deferred-dead, pending-serve, WB-slot, handoff and migration
ownership locations. It closes successful but unadmitted accept CQEs, accounts
for completed sends, gives already owed output one nonblocking flush, fences
the ring, releases reply borrows and closes/frees the retained clients. The
existing FLIP-listener destructor closes retained raw accepts. No command,
request-path source, save policy, layout lock or reader fence was changed.
The synchronous-cancel fence must run on the issuer: an early prototype on
the joining thread correctly failed with SINGLE_ISSUER `EEXIST` and was
replaced before the fixed cohorts.

The serverless shutdown witness opens the exact unlisted epoch-wait state,
a dead client pinned by the pending-serve FIFO, and an actual cancelled receive
whose CQE has not been dispatched. It checks all four mode/engine combinations,
fd closure, idempotence and a queued PONG flush. Disabling the final cleanup
fails the asserted ownership check; no probabilistic skip or tolerance is
used. The existing shutdown gate row runs both controls, with an explicit
Makefile dependency on the included witness. Twelve additional ASAN server
lifetimes kept idle, borrowed-output, WATCH/MULTI, BLPOP and pub/sub clients
open across SIGTERM, SIGINT and SHUTDOWN NOSAVE; all passed in both engines
and modes ([results](docs/wave5c/live-shutdown/results.json)).

Fixed POST zc ASAN checks passed **50 consecutive runs per engine**:
50/50 io_uring and 50/50 epoll. One io_uring release boot was refused by the
gate's quiet-core preflight during a unit rebuild; its ASAN leg passed. That
failed job is retained as `fixed-fixed-uring-22`, not silently discarded.
See [fixed-zc-summary.json](docs/wave5c/fixed-zc-summary.json) and the complete
[100-run ledger](docs/wave5c/fixed-zc.json). All repetition receipts and
complete compressed text witnesses are in `docs/wave5c/zc-receipts.tar.gz`
(extract under `docs/wave5c` to restore the per-run `gate/` directories).
The final broader cohort also
repeats the zc job with no concurrent build outside the gate.

VALIDATION-COHORTS-PENDING

`make -j32 all` plus every one of the 42 `job_production_units` targets and
the two MDBQSBR live arms succeeded. All 45 output freshness queries passed,
including `make -q all`; the phony live-arms target is checked through its two
actual outputs with matching flags. See [freshness.json](docs/wave5c/freshness.json).
`python3 tests/gates_test.py` passed all 70 tests (including the TLS wiring
and missing-oracle checks). Source labels remain **739 quick / 756 full**,
counted relative to the quick exit, and match the 756-label fixture exactly.
No row was added or retired. Protected EXPECT assignments are unchanged
from the starting commit; their existing 685/702 values remain maintainer-owned.
The standalone strict receipt check therefore **fails** in this checkout:
`EXPECT_FULL=702, fixture=756, source declarations=756`, with no missing or
extra labels ([log](docs/wave5c/fixture-validation.log)). The maintainer must
retain/set 739/756 when landing; this lane does not change protected counts.

The 12 GET/SET/MGET/MSET hot groups match both the supplied headline and
wave5b POST under the unchanged strict normalizer. Every changed body is
listed with its reason, including clone sizes and hashes:
[wave5b delta](docs/wave5c/identity/wave5b-post-changed-bodies.md),
[headline delta](docs/wave5c/identity/headline-changed-bodies.md).
The wave5b comparison has 147 changed groups: new shutdown/WB specializations,
worker/destructor changes, resolved reference-label changes, assertion-line
immediates, and compiler propagation into a few unedited dispatch/envelope
bodies. Full normalized instruction/encoding deltas are retained in
`docs/wave5c/identity/wave5b-post-deltas.txt.gz`; these differences were not
masked or treated as a reason to stop correctness testing. No throughput
conclusion follows from identity.

Final `build/tomokv` SHA-256:
`b640ac19ca60d368322fc417d08ea8d6f8f5ec4a778a08f7249f68d78bc6eace`.
Fixed ASAN SHA-256:
`477da6ee37b63d837641c0e68d9b1c39afb6e2197eb69c9057f52fae97e972d8`.

**NOT RUN:** full `tests/gate.sh iteration`, throughput benchmarks, ABBA and
PMU performance measurements; these remain with the maintainer under this
lane's authorization. No push. No new PAD arm: this is a correctness repair,
not an optimization claim. Temporary historical/diagnostic object trees are
removed; binary hashes and reproducible source-build commands are retained.
