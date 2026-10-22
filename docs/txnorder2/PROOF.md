# txnorder2 completion proof

This continues the saved lane, rather than restarting it. The source merge and
implementation commits below are retained. [RESUME-REVIEW.md](RESUME-REVIEW.md)
accounts for every path in maintainer WIP commits `397403586` and `bbcbb6252`:
all are kept; the runtime driver additionally isolates the AOF owner-data path.
No later capacity-stop commit was present at resume.

## Implementation and anchors

| Task | Implementation / evidence |
|---|---|
| 0: merge | `73e35f754` merges `a7dfb9d23`; the private EXEC mover overlay and all headline moverfix rows are retained. Identity/PRE use that merged origin, not 991d48f65. |
| 1: A′ episodes | `822d7f310`; `txn_writer_episode`, `multi_plain_write_ready`, `txn_scatter_write_ready`, `Shard::watch_place_unit` in `src/cmd/multi.inc`. One stamp per blocked writer/shard, complete local key set, all-or-none failure cleanup, `own.age_ns > stamp` wait. Applied text: `docs/txnorder/DESIGN-AMEND1.md`. |
| 2: R1–R12 | `cc7813c32`, saved exhaustive receipts in `397403586`; `tests/txnorder_episodes.cc`. Ages are stamp−1/stamp+1. Invariant-I, incomplete allocation and retirement falsifiers accompany R12. |
| 3: eager clock | `822d7f310` / `b117daa4d`; admission draws the EXEC age, retries retain it; ordinary session-entry GET/SET/MGET/MSET counts equal PRE. |
| 4: WATCH serves | `48029f52d`; production `blocking_run_direct` dirties the served key. Exact origin and Redis controls are in `origin-serve/` and `watch-oracle-final2c/`. |
| 5: WATCH FLUSH | `48029f52d`; `Shard::watch_flush` captures existing/expired watched keys before tombstones/clear. SWAPDB, database isolation and both expiry timings are checked against Redis 7.4. |
| 6: readonly WATCH | `48029f52d` / `6a56c5cc6`; finalizer rechecks dirty after the last fragment read. The owner-turn test proves the CAS/read window opened before the write and requires a null reply. |
| 7: EXEC cost | Single-shard ARRIVE, redundant scans, one-key duplicate storage/preflight and eager clocks are removed. `bbcbb6252` single-key preflight is reviewed, not silently accepted. [COST.md](COST.md) gives instruction counts per EXEC, before/after optimization, scope and remaining costs. |
| 8: main-path deltas | `9d6e99d0d` removes DB0 MGET's extra instruction per fragment; DEL/UNLINK match or improve. Scan-home helper bodies are identical. Residual MSET counts and all compiler spillover remain explicit in [COST.md](COST.md) and [IDENTITY.md](IDENTITY.md). |

D1–D10 stay as approved, including validation claims blocking writers from
placement. A′ does not replace that rule with a dirty-check alternative. Plain
writers can wait behind the finite older-unit set at their episode stamp;
newer units cannot extend it by placing writer-blocking claims. Blind groups,
scripts, blocking serves and WATCH registration acquire no writer marks.

## Busy fused owner reproduction

`7b31fd15f` fixes a separate liveness defect. The file named
`differ-hang-backtrace.log` contains a failed debugger attach, **not a useful
backtrace**. The owned-child capture in
`nx-progress-repro-owned-attach-third/3/` is the evidence: owner 7's inbox has
tail 2005/head 2004, zero NotifyMask, and an unconsumed phase-two RENAMENX task.
An older group is Executing with pending=1; a younger group is Placing and
correctly waits. No writer episode is involved.

A producer's quiet publication can leave that summary state. A split owner
repairs it in the periodic depth sweep. A fused owner was classified as Ifid,
so it used only the idle recovery path; a parked transaction keeps it busy.
The fix includes `fused_executor_context_` in the existing 100µs sweep.

`tests/txnorder_wake_unit.cc` recreates the captured inbox state, requires the
masked drain to miss it, runs the real sweep, then requires exactly one task.
`wake-before-fix/result.json` uses the **exact parent of 7b31fd15f**: fused
exits 1, split exits 0; POST exits 0 in both. `wake-control/results.json`
independently records the same fused failure against merged origin/cpp.
The new gate row runs both modes; no claim predicate is weakened.

## Runtime plan

[runtime-coverage.json](runtime-coverage.json) indexes **all 215 original
rows**, their commands, selected receipts, binary hashes and limitations:

| Arm | Selected outcomes |
|---|---|
| POST | 155 PASS |
| merged-origin PRE | 11 PASS, 45 FAIL |
| barrier-off negative | 4 FAIL on the mandatory mechanism witness |

These are not relabelled as 215 successful tests on one binary. The resumed
153 POST rows use immutable SHA `5950eb30…` (`runtime/final2b/`); the two focused
differential receipts are the earlier completed `eb6e80dc…` run (`runtime/last/`).
The final `5bfa95e7…` binary additionally runs the complete touched-job gate
matrix, including the full split and armed fused differential jobs. The only
production change after the resumed run is DB0's local owner-argument stack
residence; final path fixtures and gate jobs use that final spelling.

Coverage includes both modes, atomic 0/1, database 1/16, AOF prepare/replay,
8192-repeat EXEC/bare NX, original transaction audits, Stage B/movers, G1–G6,
read-local witnesses, broad batteries, writer/snapshot/FLIP, crossed WATCH,
fresh boots and a–d. Fresh WATCH runs retain all ten boots per declared arm.

PRE passes are retained as passes; they are not advertised as negative
controls. The first b-family failure on a missing INFO counter is invalid and
superseded by `runtime/b-pre-last/`, which fails exact final data. Corrected
c-family accounting is in `runtime/c-final/`. Barrier-off controls prove the
required witness fails when its mechanism is removed; the remaining placement
protocol can still keep their data correct, so they are **not** evidence of a
lost-update failure.

The pre-txniso batteries ran in full. Their X1 DEBUG-instrumented sub-arm is
**NOT RUN as a semantic PRE control**: merged origin lacks that hook. The
unknown-command result is not counted as defect evidence. Actual D/V/S data
failures and W3/Z1 progress/window failures are retained separately.

### Harness sequencing and oracle evidence

`7c667cbc4`, `8a1e4f18e`, `122d43569` and the reviewed WIP keep exact Redis
replies/data while adapting held windows to D1. A writer cannot be awaited
synchronously while the unit that blocks it remains held. The AOF, atomfix,
txniso and differential COPY/STORE adaptations retain a real held-window
witness, require the dependent command to remain blocked, release the holder,
then compare exact results. `execatomic.py` rearms on fresh state at most four
times only when data is correct but the window did not open; a missing final
witness fails. No tolerance or EXPECT value was widened.

`watch-oracle-final2c/results.json`: Redis 7.4.10 passes both WATCH families;
final POST passes both in all eight combinations of 1s/2s, uring/epoll and
DB1/DB16. The unmodified merged-origin PRE fails both families in all eight
combinations. The additional exact-origin owner serve fixture fails after
observing a present element, serving it, and finding WATCH still clean.

## R-family and baseline distinctions

The episode defect was introduced by the pre-amendment lane. Its meaningful
PRE is **73e35f754**, with the stamp-observation shim disclosed in
`controls/pre-instrumentation.patch`; it is **not** origin/cpp. The separate
rank-only control changes just the unconditional writer wait predicate.

* R1–R7: PRE retains the expected cycles. Rank-only breaks the single-key
  shapes but still cycles on R3/R4. Complete A′ episodes terminate all seven.
* R8: the forbidden started-only/read-before-CAS/Dekker alternatives are
  falsified. This guard itself passes PRE because D10 is retained. The positive
  gate row additionally requires the complete episode contract and fails PRE
  there; its four real WATCH handshake legs remain passes.
* R9–R11: episode lifetime/failure, bounded overtaking and ranking controls
  retain their explicit PRE outcomes in `controls/`; no missing counter is
  used as the failure.
* R12: exhaustive production-predicate explorer sees cycles in every PRE
  shape, only R3/R4 in rank-only, and none in POST. POST state/transition counts
  are 14/70, 7/35, 11/55, 11/55, 4/20, 4/20, 4/20. The invariant and leaked-mark
  falsifiers require the deliberate break to be detected.

`gate-pre-complete/` preserves the completed **own gate-job** PRE run:
16 scored failures, all 24 WATCH mode/engine/database logs, and current fixture
hash equality. This supersedes relying on a top-level partial ledger alone.
Its readonly failure reaches the final reply assertion after the held window
opened; its serve failure reaches the watcher assertion; FLUSH fails on the
exact oracle result. PRE units are positive-expectation fixtures, not tests
that turn a detected PRE cycle into a scored gate pass.

**NOT RUN:** literal merged-origin R-family and item-6 readonly mechanism
negative controls. Origin has no version-order writer episodes, and its older
readonly validation claims do not permit the post-CAS write window used by
item 6. Porting the new mechanism into origin would cease to test origin.
The pre-amendment lane controls above test those defects; origin is used for
WATCH serve/FLUSH, the wake fix, cost, identity and ordinary runtime PRE.

## Gate jobs and finish checks

Final selected gate-job run is in progress in `gate-final2d/`; it requests
every job in `resume/scope.json` through `GATE_ONLY_JOBS`. Completion and exact
counts will be recorded here after the dispatcher exits. It is a PARTIAL
correctness ledger, never a full iteration/performance/source receipt.

`resume/build-final.json` records `make all -j32`, every production-unit target,
the mdbqsbr live arms and make-q freshness. `resume/gates-test-rerun.json`
records **67/67** harness tests passing unchanged. The first run's two scheduler
fixture timeouts happened during compilation; that failed log is retained.
The rerun used disjoint CPUs after compilation, without changing a deadline.

All work uses CPUs 64–95 and ports 27800–27899. Existing gate batteries keep
16 shards and split 6:2. The four-owner a–d stress uses the design's explicit
4:4 split override; fused tests arm read-local. New WATCH rows declare and run
both network engines.

Gate counts are by collector position, not command category: txnorder2 and
txnorder_wake are collected at lines 4420/4421, before quick exit line 4503.
This continuation adds 17 rows; the whole unmerged lane adds **DQ=DF=31** over
a7dfb9d23 (10 txnfix/txnfix2 + 4 txnorder + 17 txnorder2). Required maintainer
counts are **716 quick / 733 full**, from 685/702. Protected EXPECT assignments
remain unchanged.

## Limits retained for review

D3 blind-group restarts remain possible; the episode fairness result is not a
worst-case bound on those restarts. Invariant-I's monotonic-clock and FIFO
dispatch assumptions remain the approved design assumptions. The existing
MGET cut does not retain arbitrary unversioned history. Active expiry and
eviction versus read claims remain the design §6 owner decision, not a new
claim of this lane. Both eviction selectors (`flatstore.h:2405,3069`) and
version admission (`flatstore_atomic.inc:596`) reject victims needing a live
version; this was rechecked in the merged source. It does not establish a
stronger blanket eviction pin for every read claim.

Identity differences, non-identical TLS additions, cold Server growth and
the limited type-A PAD are disclosed in [IDENTITY.md](IDENTITY.md). Hardware
cycles/instructions/IPC, throughput, the main-command null and EXEC merit
cells are **NOT RUN**, reserved for the maintainer. No throughput claim is
made from the instruction audit.
