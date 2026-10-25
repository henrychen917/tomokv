# FLIP controller correctness — lane ctlfix

## ctlfix

Base: `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`. Branch `cx-ctlfix`.
Correctness work only; no throughput claim. All lane builds and test processes use
CPUs 48–63, with listener ports confined to 35800–35899. No push.
Fix commits: CT4.1 `337cad6bc`, CT4.2 `8fcc3feee`, CT4.7 `a693400c7`.
The frozen PRE tree's **227 production/build/vendor inputs match 05a5e01a9**;
the four test overlays are listed in `docs/ctlfix/pre-source-identity.json`.

### CT4.1 completion consumption and state table

REPRODUCED through `tests/gate.sh`, job `flip_unit`, using the existing
`CoreConcurrencyTest::Fixture<false>`: 8 logical workers, 6 IO + 2 EX, 16 shards,
database 0, load balancers off, no network/worker loop. An automatic 6:2 → 4:4
completion followed by accepted manual 4:4 → 6:2 before the monitor tick produced
`completed=2 phase=waiting-flip consumed=0` on PRE. The first attempted run failed
to compile because the embedded fixture needed `TOMO_CORE_CONCURRENCY_TEST`;
`ct41-pre-repro.log` is the armed reproduction, not that infrastructure failure.

The existing `pending_completed_` becomes the monitor's monotonically consumed
completion cursor as well as its automatic request's baseline. The monitor consumes
the entire newly completed count once under the admission mutex after acquiring
Idle. No event queue, allocation, hot-path bookkeeping, or layout field is added.
Only one isolated completion at the expected target without an intervening refusal
can contribute automatic cost. Any manual/ambiguous batch cancels the hypothesis
and learns a fresh anchor at the actual placement. Admission rejects stale
controller evidence under the same mutex, without consuming its completion.
Cancel the automatic trigger's attribution too: the eventual anchor must neither
credit a move nor penalize a null maneuver after manual intervention. Extending
the schedule through `anchor()` caught this in the first POST implementation
(`manual-anchor-before`, failed); the corrected implementation passes the same
row (`manual-anchor-after`) with confirmations and model margin unchanged.

Here A is the automatic request, M a manual request, O a monitor observation;
“settle” means discard the stale hypothesis and settle at the live placement.
Accepted same-target no-ops count as completions in the existing actuator.

| Ordering / observation | Completion handling | Controller action |
|---|---|---|
| A active; O (with or without a refused M) | No completed transaction consumed | Wait for Idle; defer forced trigger |
| A completed; O; no M | Consume A once; price isolated cost | Enter A's requested Seeking/Settling phase |
| A completed; M completed; O, different final target | Consume both once; discard combined cost | Settle |
| A completed; M completed; O, same final target/no-op | Consume both once; discard combined cost | Settle; never mistake matching target for isolated A |
| A completed; O; M completed; O | Consume A then M once each; retain only A's isolated cost | First continue A, then settle |
| A refused; M completed; O | Consume M; refusal makes attribution ambiguous | Settle without outcome/cost learning |
| M refused while A active; A completed; O | Consume completion once; conservative ambiguity handling | Settle without attributing an outcome |
| A refused; O; no completion | No completion to consume | Existing settle/return path |
| M active; O in any other phase | No partial completion consumed | Wait for Idle |
| M completed; O in BootPending/Measuring/Seeking/Settling/Anchored | Consume complete batch once | Settle |
| M completes between sampling and automatic admission | Admission count check rejects stale request | Next O consumes M; settle |
| Forced trigger before/during/after any completion above | Consume completed count first; isolate cost only if valid | Restart Measuring after Idle |
| Repeated O with unchanged completion count | Consume nothing again | Continue current phase; no duplicate cost/learning |

These equivalence classes cover arbitrary repeated M completions: the count delta
consumes every member of a batch, and any batch beyond the one isolated A is
intervention. A request admitted just after the locked observation belongs to the
next observation. The monitor does not reconstruct intermediate manual targets.

### CT4.2 IO-only boot measurement

REPRODUCED on frozen PRE through the same gate job. The existing in-memory boot
fixture publishes deterministic fingerprints and feeds 6000 completed commands
per 1-second tick at 6:2 / 16 shards. PRE enters boot measurement once, spends
53 ticks in Measuring, and still reports samples 0 / cap 15. No sockets or
timing-dependent arming are involved.

Count every accepted stabilized rate reading against the budget before asking
whether both roles supplied enough work for a demand estimate. Missing role
evidence contributes no demand draw. At the cap, record `hold-no-demand`, clear
the requested debug seek, and settle at the live split. The regression includes
IO-only, intermittent executor work, and continuous executor work, and requires
Anchored plus the maneuver sampling arm off. The cap remains a count of accepted
readings, not a promise about elapsed time during unstable/invalid windows.

### CT4.7 raw-model calibration

REPRODUCED on frozen PRE through the gate job with 129 synthetic production
hypotheses, each raw gain +1: first miss, 127 hits delivering +0.25, final miss.
The first miss makes kappa 0.5. PRE then feeds calibrated predictions back into
the learner and finishes at **0.496022121**, instead of **0.251923077**.
POST feeds raw gain to both the hit and returned-miss call sites and matches the
raw-unit formula at every prefix (maximum error below 1e-12). Its predicted sum
is 129; PRE's is 64.517398655. With increasing quarter-delivery evidence, POST
converges to one quarter; PRE approaches one half before the final miss.

The verification/cost model still uses the calibrated forecast. Refinement also
retains its original units by comparing delivery to the *saved pre-outcome*
kappa times the raw prediction; using the newly learned kappa here would change
that independent policy. The test checks this on every successful hypothesis.

The initial calibration attempts failed their arming guard: role IDs change
across real FLIP planning, so a fixed physical-thread demand pattern ceased to
provide executor operations. The final fixture follows each thread's actual
role on each fresh draw. No failed arming attempt counts as reproduction.

### Gate accounting

The existing `flip controller model unit` row is extended with deterministic
production-controller schedules. Its original arithmetic tests remain present.
No added or retired ledger label: DQ=0, DF=0. The row is collected before the
quick-tier exit. `EXPECT_QUICK` and `EXPECT_FULL` remain untouched.
Specifically, `collect_job flip_unit` is at `tests/gate.sh:5107` and the touched
`core_units` route fixture is collected at line 5129; both precede the quick-tier
exit at line 5349. The route fixture now distinguishes an already consumed
completion from the completion whose transition it is testing, and permits only
that cursor's expected byte change in its unrelated-state mask.
The extended `flip_unit` depends on `production_units`, which finishes shared
release-object writes before the new fixture links them. The final PRE, POST and
PAD-A unit receipts all exercise that dependency through `GATE_ONLY_JOBS`.

Source-label reconciliation: **785 declarations / 785 fixture labels**, with
identical multiplicities. Existing expectations remain **768 quick / 785 full**.
The independent checker result is `docs/ctlfix/label-fixture.json`.

### Binary identities and controls

| Arm | Path | SHA-256 |
|---|---|---|
| PRE, 05a5e01a9 | `build/tomokv-PRE` | `f300057c10b8664da9a4ded59403be3482870f5507ef36611f3235d294f72fbe` |
| POST | `build/tomokv` | `9ce7cd18c4900705c71f31780b12a04c518ffceb28c4ac3287f1a50dcd73c27d` |
| PAD-A | `build/tomokv-PAD-A` | `c48293d8990ee9da0c4604c97548a9dec5f51fb752ac6b5b67b6951bd4a72705` |

**PAD kind A: behaviour twin, PRE behaviour with POST text size/layout.**
`tools/ctlfix_artifacts.py pad` changes the two constant return immediates of
`ctlfix_correctness()` (DB0 and multi-DB variants). It verifies the exact x86
instruction sequence, preserves CET entry instructions, and proves that every
other ELF byte, section, symbol address and size is identical. There is no
runtime knob selecting the legacy branches. The corresponding unit twin, run
through `flip_unit`, reproduces all three PRE defects. Restoring the POST unit
passes every regression, including the additional refusal, in-flight manual,
returning-miss and stale-admission schedules.
The manual-anchor guard is inert on the legacy branch: its only new path to
`last_trigger=None` is inside corrected completion handling. PRE reaches an
anchor after `start_maneuver()` has set a non-None trigger.

The unchanged strict linked normalizer (`tests/reorder_noop.py`, via the existing
wave4 inventory) compares **9332 bodies**, with **151 changed**. All **80 linked
GET/SET/MGET/MSET bodies are identical**, including actual xshard execution and
commit paths. The existing object relocation normalizer independently checks
**74 command-family bodies**, all identical. These are different inventories;
the counts are not added. Full inventories and changed bodies are retained under
`docs/ctlfix/`. Dispatch/loop compiler changes remain in the merit arm: identity
is a proxy, not a performance verdict. GNU size's text total is 9,297,053 PRE and
9,299,921 POST/PAD-A; data and BSS totals are unchanged. No layout field was added.

`make -j16 all` succeeded. An independent `make -q` inventory checked **44/44**
targets fresh: `all`, every target named by `job_production_units`' main make,
and its `mdbqsbr-live-arms` target. See `docs/ctlfix/make-freshness.json`.
Both final PRE and POST gate archives also contain all **43** production-unit
readiness markers from the gate's own build/freshness checks.
After archiving proof, duplicate PRE build outputs are removed; its four command
objects, frozen sources, the three binary arms, and POST targets are retained.
`build-cleanup.json` records the exact cleanup and retained-object hashes.

### Maintainer merit request: generic 14 cells

Use the gate's instrument, unchanged load plans, matched offered load, and a
contemporaneous same-binary null for **PRE/POST/PAD-A**. The exact existing cells
are copied verbatim to `docs/ctlfix/merit-cells.txt`:
`h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h63,h64`.
The cell-file digest is
`1519aa1b952c863b001eef4c6700479e4c8d9a9099d00bcc0bb77b85ce1fd631`;
the source cell inventory and measurement-plan hashes are recorded in
`docs/ctlfix/merit-inputs.json`. Preserve the instrument's geometry, persistence,
knobs, payloads and per-cell score type.

Report per-cell matched-load rate, cycles/op, instructions/op, IPC, p99 and
p99.9. Use the gate's existing null-derived acceptance rule and each cell's
rate/latency score; do not average away a regressing cell or infer merit from
instruction identity. Compare PRE/POST, PRE/PAD-A, and POST/PAD-A where a cell
moves. An actual behavior effect should move POST while its PRE-behavior PAD-A
control stays flat. The default-off controller has no claimed throughput gain;
this request checks regression and code-layout effects of the correctness fixes.
The merit verdict is the gate's per-cell PASS/FAIL for POST versus PRE across
all 14 cells; a failed cell needs investigation even when the command bodies match.

**NOT RUN, owner-reserved:** throughput/performance measurements, merit cells,
and the full `tests/gate.sh iteration`. All live invocations in this lane are
correctness tests or individual gate jobs; no throughput result is claimed.

**NOT RUN:** the standalone `tailgen client-lb outstanding bound` row. It is
outside `GATE_ONLY_JOBS`, and its documented geometry needs 16 load cores in
addition to the server cores, exceeding this lane's 16-core allocation. Its
measurement load generator remains with the maintainer.

### Broad correctness proof

Every new/touched row was run through `tests/gate.sh`'s own `GATE_ONLY_JOBS`
interface, with its declared legs intact. These are partial job runs, not a full
785-row gate result. Counts below include each selection's release prerequisite;
`production_units` is an unscored build dependency.

| Receipt under `docs/ctlfix/` | Result | Interpretation |
|---|---|---|
| `post-unit-final` | 2 ok / 0 FAIL | Original arithmetic plus all three production regression selectors pass |
| `pre-unit-final` | 1 ok / 1 expected FAIL | All three selectors execute and reproduce their defects on frozen PRE |
| `pad-unit` | 1 ok / 1 expected FAIL | PRE-behaviour twin reproduces the same three defects |
| `post-final` | 91 ok / 1 FAIL | Initial listener leg cannot bind TLS port 35812; other rows pass |
| `pre-broad` | 40 ok / 2 FAIL | Expected regression failure plus the same listener boot collision |
| `post-epoll`, `pre-epoll` | 15 ok / 0 FAIL each | Complete FLIP, flipctl, saturation and both stationary balancer jobs |
| `post-feature-matrix` | 38 ok / 0 FAIL | 35 feature cells, both network-mode rows, release |
| `post-rlcache` | 3 ok / 0 FAIL | Both cache rows and its build prerequisite |
| `listener-post-final`, `listener-pre-final` | 5 ok / 0 FAIL each | All four listener rows / 16 engine-atomic-direction-outcome legs, plus release |

The broad selections cover config, flip-unit, all nine core-unit rows (including
ASAN/UBSAN and TSan), flipfix and balancer planner units, all seven boot grammar
rows, stationary balancing in both modes, flipctl, FLIP state/load/TTL,
close/churn, signal shutdown, stale epoll registrations, listener conservation,
and saturation. POST also runs both atomic values of the debug and fused
batteries. The close/churn rows retain both engines and enable `flip-auto 1` on
the strict client-arrival churn leg. The epoll wrapper supplies a default only;
explicit engine legs remain intact. Feature cells include all 32 declared
mode/read-local/client-LB/reorder/flip-auto combinations plus three geometry
extras, including the fused-mode auto-FLIP refusal cases.

The repeatable job entry point is `taskset -c 48-63 bash
 docs/ctlfix/run-proof.sh {post-final,pre,epoll,matrix,pad}`. Every gate invocation
uses server CPUs 48–55 and client CPUs 56–63, ratio 6:2 and 16 shards except where
an existing row explicitly declares another geometry. Full logs, job fragments,
per-leg output and manifests are in `docs/ctlfix/gate-receipts/`; completed jobs
are archived with a SHA-256, and generated binary/persistence files are omitted.

The isolated `taskset -c 48-63 env GATE_TEST_PORT=35899 python3 tests/gates_test.py`
run passed **72/72 outer tests**; its nested 14-test identity self-test also passed.
The final freshness inventory passed **44/44** and source labels matched
**785/785**. The final listener jobs both used the bind-verified reservation
35841–35843 and passed every leg.

The standard differentials use the unchanged `tests/differ_gate.sh`, all 47
registered generators, both atomic values, the permanent and historical seed
set plus each run's rotating seed, and the standard repeated multi-key legs.
Split mode also runs the complete mode-equivalence matrix. Armed-fused mode
requires positive read-local execution witnesses for each atomic value; its
existing SORT exclusion requires split 6:2 and is reported as SKIP, not PASS.

The engine queues run concurrently as correctness tests within the assigned
16 CPUs: uring targets/oracles on 48–55 and clients on 56–63, epoll
targets/oracles on 56–63 and clients on 48–55. Server core groups are disjoint;
clients share cores with the other queue's server. This is not a performance
experiment. The live affinity snapshot checked all 35 server/oracle threads
inside 48–63. Each queue reserves distinct consecutive target/oracle/control
ports (uring 35861–35879, epoll 35881–35899); exact selections are in the
per-matrix `*-ports.json` receipts. The initial sequential outer loop is retired
only after its active split matrix finishes normally; no test leg is interrupted.
`differ-scheduling.json` records that scheduling change.

| POST standard matrix | Result | Seeds |
|---|---|---|
| uring / split | **663 PASS, 0 FAIL**; 16/16 equivalence cells | 7, 19, 20, 23, 21, 22, 24 |
| epoll / split | **663 PASS, 0 FAIL**; 16/16 equivalence cells | 7, 19, 20, 23, 21, 22, 25 |
| uring / armed-fused | **650 PASS, 0 FAIL**; both read-local witnesses pass; 14 declared SORT skips | 7, 19, 20, 23, 21, 22, 26 |
| epoll / armed-fused | **650 PASS, 0 FAIL**; both read-local witnesses pass; 14 declared SORT skips | 7, 19, 20, 23, 21, 22, 27 |

All four matrices record comparison coverage for **232 of the source inventory's
245 registered commands**: 662 leg artifacts per split matrix and 648 per
armed-fused matrix. `differ-final-summary.json` records the exact results, both
read-local witnesses, seed sets and hashes of the unchanged standard proof
drivers. All four return codes are zero. The remaining 13 commands
are explicitly listed in each coverage receipt; this is not an all-command
coverage claim. Full comparison output, coverage counters, seed allocations and
mode-equivalence evidence are archived under `docs/ctlfix/differ-receipts/`.
After verifying the archive hashes and file inventories, generated differential
data directories were removed. All master logs, return codes, port receipts and
archives remain. The retained seed history includes the earlier infrastructure
failures; no failed seed was erased or excluded from these standard runs.

Earlier attempts are retained, not counted as final proof. The first POST broad
run had five failed rows after a readiness TCP self-connection occupied
35800→35800 in TIME_WAIT; the log also captured a readiness PING echoed back.
The fresh-port retry passed all nine FLIP rows, but two uring debugger boots in
the listener job failed binding the adjacent TLS port 35812. The final broad
POST and PRE selections also encountered that TLS-port collision on their first
listener leg. These are pre-window boot failures; server logs record
`bind tls-port: Address already in use`. The separate listener retry binds all
three allocated ports before invoking the entire unchanged job. No timeout or
assertion was weakened.

My first two differential invocations incorrectly put Redis on target+2, the
port reserved by `climon_reader_control()`. All climon legs stopped at bind,
and the missing comparison witnesses correctly failed the coverage summary.
The two complete failed matrices and the command error are retained in
`differ-receipts/` and `differ-port-error.json`. The incorrect-port loop was
retired after its current matrix completed; its epoll matrices were not started.
The corrected standard matrix uses consecutive target/oracle/control ports,
preserves every suite and the harness's complete seed history, and runs after
the preceding jobs finish. Those infrastructure-failure seeds remain in the
harness's permanent replay history.

The initial `python3 tests/gates_test.py` attempt recorded six scheduler-fixture
timeouts while compilation was active. Its log is retained; the isolated rerun
passed without a timeout or assertion change. Separately, an
unintended duplicate PRE queue was stopped; incomplete attempts are retained as
interrupted, with details in `proof-interruption.json`. These attempts do not
count as completed proof.
