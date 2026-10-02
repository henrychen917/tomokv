lanefull2 — 2026-10-02

The reset check now excludes one settle round, waits for stable deferral counters, and then requires the original exact control/reset equality. The synthetic transient passes; leaving the cap set and removing the settle round each exit 1 at `cap reset restores derived-lane pressure`. Live validation remains for mainline. No server, benchmark, load generator or gate was run, and nothing was pushed. All builds and serverless tests ran under `taskset -c 112-127`.

Worktree/branch: `/home/user/Projects/cx-cleanup-lanefull`, `cx-cleanup-lanefull`. Launch HEAD, before the required merge, was `7ed86542b452205febe2a6e6dbacc6a5ebff8105`. The first mutation was merging `origin/cpp` at `11b2cbcff355191500c179383679281d7cfc7082`. Merge commit `c909c97c6` preserves both lanes' includes, selectors and route checks in `tests/core_concurrency_unit.cc`.

**Diagnosis from the code.** `src/cmd/t_server.cc:967` validates the DEBUG cap and calls the setter; `src/core/server.h:2979` only stores the new shared cap word with relaxed ordering. Resetting to zero clears the override. It does not synchronously clear lane entries, deferred input, per-reader cached admission capacity, the pressure window, or statistics, and its OK is not an acknowledgement from every reader.

Each split reader drains local reads, decrements `lane_pressure`, and adopts the cap in `src/core/rl2s.cc:48`; the fused path does the corresponding pressure decrement and cap adoption in `src/core/ex_loop.h:563`. Zero derives to `kInboxSlots` (1024). A real lane-full event arms eight rotations (`ex_loop.h:65`, `:323`); quota deferrals do not rearm that window. The parser computes a connection's quota from the current pressure/cap and leaves refused frames at `rpos` for a later pass (`src/core/io_loop.h:3443`). Consequently, a DEBUG reset alone is not a drain barrier: work already admitted or deferred, cached capacity and pressure can outlive the command on other readers.

There is an important limit to the supplied diagnosis: this battery reads every reply before ending the capped phase. The code therefore supports delayed capacity adoption/residual pressure, but does **not** establish that this battery still has uncompleted capped-phase GET frames at reset. The reported `7 / 7` events are consistent with transient scheduling/admission state; their precise live cause has not been reproduced here. No production defect is established by the old immediate equality failure.

**Exact new semantics.** Only the third clean phase changes (`tests/read_local_lane.py:199`). After `DEBUG READ-LOCAL-LANE-CAP 0`:

1. Run exactly one uncounted clean round on the same 16 connections, each with the same 64 pipelined GETs: 1,024 reads. Check ordered replies, the existing 20-second round limit, exact local completions and zero fallbacks. Do not retry this round to erase failures.
2. Poll `INFO stats` every 10 ms until **both** `read_local_defer_lane_full` and `read_local_defer_quota` have remained unchanged for at least 50 ms. Any change restarts the quiet interval, not the two-second absolute deadline. Bound each INFO socket wait by the remaining deadline, then restore the control socket's prior timeout. Missing counters or retired INFO keys still fail through the existing counter reader.
3. Use the final stable snapshot as the restored phase's baseline. Drive the existing six clean rounds (6,144 reads), retaining exact hits, zero fallbacks, ordered replies and liveness. Require each restored deferral delta to equal its control delta exactly; for the reported control this is `0 / 0`. No tolerance, counter reset or new retry is introduced.

The named reset check reports any unequal measured delta as:

```text
deferrals persist after a drained settle round: cap reset leaks state
```

It includes both complete delta dictionaries. A counter that never settles instead fails `cap reset restores derived-lane pressure: settle deferral counters did not drain within 2.00s`, so an unsuccessful drain is distinguishable from deferrals during the subsequent measured traffic. Idle INFO stability alone cannot prove that the cap was reset: the restored traffic supplies that discrimination.

The deterministic pressure mechanism remains `CAP=8`, `CONNS=16`, `DEPTH=64`, `ROUNDS=6`. The existing three-attempt, fresh-connection rearm remains limited to an unentered capacity/quota window. AST comparison against the merge commit confirmed that `assert_retired_keys_absent`, `counters`, `burst_round`, `drive`, and all seven other `rep.check` calls are unchanged. The mixed order/RYOW, mixed liveness, >=95% mixed local-read floor and mixed cap-reset block are unchanged. The battery still emits eight checks.

**Serverless results and limits.** `--self-test` replaces connections, traffic generation and time with an in-memory counter trace while executing the actual `main` phase loop, counter parsing, settle/polling helpers and verdicts. The first traffic after a reset produces the supplied seven-event transient; an idle INFO poll cannot consume it. Cap=8 generates continuing pressure. These are synthetic assumptions, not measured server counters. This proves phase accounting and assertion discrimination; it does not prove live scheduling, networking, reply order or RYOW. The existing C++ route unit separately exercises production admission paths without starting a server.

| Check or control | Exit | Observed result |
|---|---:|---|
| `--self-test` | 0 | All eight checks pass; control/reset deferrals `0/0`; exactly one settle round excluded. |
| `--self-test delayed-drain` | 0 | Counter changes at logical 20 and 40 ms restart the quiet interval; measurement waits at least another 50 ms. |
| Throwaway cap-left-set copy | 1 | Named reset check fails; restored full/quota `672/672`, control `0/0`; the other seven checks pass. |
| Throwaway skip-settle copy | 1 | Named reset check fails with the original trace: restored hits 6,144, fallbacks 0, full/quota `7/7`, control `0/0`; the other seven checks pass. Polling remains in this mutant. |
| `--self-test leak-full` | 1 | Named reset check fails on `6/0`; lane-full comparison is independently load-bearing. |
| `--self-test leak-quota` | 1 | Named reset check fails on `0/6`; quota comparison is independently load-bearing. |
| `--self-test never-drains` | 1 | Named drain assertion fires at the two-second logical deadline; there is no unbounded wait or skip. |
| Python byte compilation and `git diff --check` | 0 | Pass. |
| C++ build, after fixture adaptation below | 0 | `build/signalacct-core-unit` builds. |
| `build/signalacct-core-unit route` | 0 | Route assertions pass, including lanefull GET/MGET in both 1s/2s at databases 1/4, INFO checks and merged flipreport checks. |

The two throwaway copies and their command/exit/output logs are under `build/lanefull2/`, alongside `leak-full.log`, `leak-quota.log`, `never-drains.log`, the build logs and `core-route.log`. No negative edit touches production or the committed battery. The skip-settle mutant intentionally retains the new failure wording while bypassing its settle prerequisite; its `7/7` result reproduces the old failure numerically on a synthetic trace, not on a live server.

Reproduce the positive traces from the worktree root:

```bash
taskset -c 112-127 python3 tests/read_local_lane.py --self-test
taskset -c 112-127 python3 tests/read_local_lane.py --self-test delayed-drain
taskset -c 112-127 python3 -m py_compile tests/read_local_lane.py
```

Recreate the requested throwaway mutations; each old string must occur exactly once:

```bash
taskset -c 112-127 python3 - <<'PY'
from pathlib import Path
source = Path('tests/read_local_lane.py').read_text()
out = Path('build/lanefull2')
out.mkdir(parents=True, exist_ok=True)
changes = {
    'cap-left-set': ('for phase, cap in enumerate((0, CAP, 0)):',
                     'for phase, cap in enumerate((0, CAP, CAP)):'),
    'skip-settle': ('base = settle_reset_lane(ctl, conns, shared, values)',
                    'base = wait_for_lane_drain(ctl)'),
}
for name, (old, new) in changes.items():
    assert source.count(old) == 1, name
    (out / (name + '.py')).write_text(source.replace(old, new, 1))
PY
# Each command below must exit 1 at the named reset or drain assertion.
taskset -c 112-127 env PYTHONPATH=tests python3 build/lanefull2/cap-left-set.py --self-test
taskset -c 112-127 env PYTHONPATH=tests python3 build/lanefull2/skip-settle.py --self-test
taskset -c 112-127 python3 tests/read_local_lane.py --self-test leak-full
taskset -c 112-127 python3 tests/read_local_lane.py --self-test leak-quota
taskset -c 112-127 python3 tests/read_local_lane.py --self-test never-drains
```

**Merge compatibility.** The first C++ build failed because mainline commit `5bd61cca9` removed unused parser template parameters. `tests/lanefull_checks.inc:47` still supplied seven arguments. The test now calls `parse_and_dispatch<false, 0, true, true>`: unchanged `NoBorrow=false`, `BatchOps=0`, `IoPipe=true`, `SplitLocal=true`, with the removed false parameters omitted. Its traffic and assertions are unchanged. The initial diagnostic is retained in `build/lanefull2/build-core.log`; the successful rebuild is in `build-core-retry.log`. Both commands below then passed:

```bash
taskset -c 112-127 make -j16 build/signalacct-core-unit
taskset -c 112-127 build/signalacct-core-unit route
```

**Mainline handoff.** On the merged tree, run exactly:

```bash
tests/gate.sh iteration
```

Use the gate's correctness geometry: 16 shards, `GATE_CORES=0-7`, six IO plus two EX threads. This lane did not substitute a default-server boot or change the pressure shape. The existing live lane-admission row must pass all eight checks with exact post-drain control/reset equality. A live run of the cap-left-set throwaway battery against that same geometry must still fail the named reset check; that live negative remains unrun. The skipped-settle failure is already serverless-provable as above; reproducing its actual scheduling transient and validating the settle interval on the real server require mainline's live run.

No gate row is added or retired. The lane row is at `tests/gate.sh:1586`, before the quick-tier exit beginning at `:2877`; delta is **0 quick / 0 full**. `EXPECT_QUICK=446` at `:261` and `EXPECT_FULL=463` at `:262` remain untouched. `git diff c909c97c6 -- src tests/gate.sh` is empty. The earlier LaneFull/INFO production retirement, confirmed null on 14 cells by mainline at launch, stays as is; this test fix makes no new performance claim and requests no new measurement arms.

Commits before this report: `c909c97c6` (mainline merge), `585e39c60` (settle/drain and serverless controls), `2bc4e87a7` (test-only parser signature adaptation).

**Required launch diff.** Exact `git diff 7ed86542b452205febe2a6e6dbacc6a5ebff8105 --stat`, including this report. Source, gate and other large changes in this view arrived through the required mainline merge; they are not lanefull2 edits.

```text
 MEASURE-REQUEST-cleanup-flipreport.md             |   378 +
 MEASURE-REQUEST-cleanup-iotemplates.md            |   246 +
 MEASURE-REQUEST-cleanup-probeadapter.md           |   193 +
 MEASURE-REQUEST-cleanup-ringmarker.md             |   412 +
 MEASURE-REQUEST-cleanup-tlsserve.md               |   395 +
 MEASURE-REQUEST-lanefull2.md                      |   181 +
 MEASURE-REQUEST-nullpublish.md                    |   339 +
 MEASURE-REQUEST-nullpublish2.md                   |   238 +
 MEASURE-REQUEST-nullpublish3.md                   |   328 +
 MEASURE-REQUEST-nullrefresh.md                    |   242 +
 MEASURE-REQUEST-nullrefresh2.md                   |   163 +
 MEASURE-REQUEST-nullrefresh3.md                   |   203 +
 MEASURE-REQUEST-nullrefresh4.md                   |   206 +
 MEASURE-REQUEST-nullrefresh5.md                   |   224 +
 Makefile                                          |     6 +-
 src/cmd/multi.h                                   |     2 -
 src/cmd/multi.inc                                 |     8 -
 src/core/flipctl.cc                               |     1 -
 src/core/flipctl.h                                |     2 +-
 src/core/genthread.cc                             |     2 +-
 src/core/io_loop.h                                |   123 +-
 src/core/reorder.cc                               |    98 +-
 src/core/rl2s.cc                                  |     2 +-
 src/net/uring.h                                   |     5 -
 src/net/wb.h                                      |   228 +-
 src/persist/aof.cc                                |     2 -
 src/snapshot/snapshot.cc                          |     2 -
 src/store/flatstore.h                             |    84 +-
 tests/_abba_test_fixtures.py                      |    17 +
 tests/_nullrefresh_test.py                        |  1137 +
 tests/abba_binaries.py                            |   469 +
 tests/abba_ceiling.py                             |    79 +
 tests/abba_evidence.py                            |   226 +-
 tests/abba_instrument.py                          |    94 +-
 tests/abba_null_sampling.py                       |    81 +
 tests/abba_reorder_control.py                     |   240 +
 tests/abba_saturation.py                          |    11 +
 tests/abbagate.py                                 |   238 +-
 tests/core_concurrency_unit.cc                    |     5 +-
 tests/fixtures/nullpublish-campaign6-compact.json |   383 +
 tests/fixtures/nullrefresh-ledger-labels.json     |   482 +
 tests/flipctl_unit.cc                             |     5 +
 tests/flipreport_checks.inc                       |    87 +
 tests/gate.sh                                     |    26 +-
 tests/gate_ledger_fixture.py                      |   306 +
 tests/gate_measurements.json                      | 27782 +++++++++++++++++++-
 tests/gate_measurements.py                        |   107 +-
 tests/gate_receipt.py                             |   441 +-
 tests/gates_test.py                               |    89 +-
 tests/lanefull_checks.inc                         |     2 +-
 tests/load_calibration.py                         |   117 +-
 tests/multidb_boundary_unit.cc                    |     2 +-
 tests/multidb_db0_unit.cc                         |     5 +-
 tests/multidb_unit.cc                             |    15 +-
 tests/netcmd_unit.cc                              |     2 +
 tests/nullpublish_refreeze_test.py                |   153 +
 tests/probeadapter_checks.h                       |   160 +
 tests/r7shadow_sync.py                            |    37 +-
 tests/read_local_lane.py                          |   188 +-
 tests/rehash_waits_unit.cc                        |     6 +-
 tests/reorder_engagement_unit.cc                  |    92 +-
 tests/reorder_noop.py                             |    17 +
 tests/tlsserve_checks.inc                         |   312 +
 tools/flipreport_proof.py                         |   331 +
 tools/iotemplates_proof.py                        |   503 +
 tools/nullpublish_refreeze.py                     |   197 +
 tools/probeadapter_proof.py                       |   311 +
 tools/ringmarker_proof.py                         |   225 +
 tools/tlsserve_proof.py                           |   384 +
 69 files changed, 37882 insertions(+), 1795 deletions(-)
```

The narrower `git diff c909c97c6 --stat` shows only this lane's work after the merge:

```text
 MEASURE-REQUEST-lanefull2.md | 181 +++++++++++++++++++++++++++++++++++++++++
 tests/lanefull_checks.inc    |   2 +-
 tests/read_local_lane.py     | 188 ++++++++++++++++++++++++++++++++++++++++---
 3 files changed, 361 insertions(+), 10 deletions(-)
```
