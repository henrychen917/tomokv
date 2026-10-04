Climonfix2: the missing collection is fixed and committed. The extractor now declares
**484 full rows = landed 476 + 8**, and **467 quick rows = landed 459 + 8**.
The serverless gate suite passes 58/58. The receipt chain is **not green**: its
fixture guard correctly refuses the eight additions while the maintainer-owned
counts and label fixture remain at the landed values, as the addendum requires.

Worktree/branch: `/home/user/Projects/cx-climonfix`, `cx-climonfix`.
Launch HEAD: `b997807081b47bb0a5708f832dcf26963e2d9bd2`.
Fetched/merged `origin/cpp` at `068fdb816d63d9adf4bbfd2aa5a11d57cd7c4615` first;
merge commit: `0cade4ce57db934a0c5b1ea9851913f32f39ab46`.
Fix/test commit: `036e8273f`.

The merge's additive build/readiness-list conflict retains shutdown, splitlocal,
netcap, flushfix and both kTLS targets. The EXPECT conflict takes origin/cpp's
459/476 verbatim; the lane's previous 462/479 belonged to the older 454/471 base.
No new count is installed. Both EXPECT lines and the complete label fixture are
byte-identical to origin/cpp. The launch-to-final diff consequently includes the
incoming mainline fixture/count changes; those are merge changes, not a lane
fixture synchronization.

Diagnosis and correction:

- `tests/gate.sh:983` already schedules `climonfix` in the job inventory.
- `tests/gate.sh:1257` defines its shutdown policy row and 2 modes x 3 stop rows;
  `tests/gate.sh:2793` retains its production-unit dependency.
- Without a collector, the real source extractor sees only the mask addition:
  477 full rows, not the promised 484.
- `tests/gate.sh:2855` now calls `collect_job climonfix`, immediately after the
  ring-unit collector at 2852 and before the quick exit at 2997.
- `tests/gates_test.py:1601` requires exactly one climonfix collection in the
  existing real-coordinator test, for iteration, push, release, full and quick.
  Its workload boundaries are stubbed; it starts no server or benchmark.

The core/waits job bodies pinned by TSANWiring are unchanged from origin/cpp.
This follow-up changes only gate wiring and its regression assertion, not runtime
source, layouts, knobs or snapshot format. No build or new performance comparison
is needed for those five lines. The original live/performance obligations remain
in `MEASURE-REQUEST-climonfix.md`. No server, benchmark, live test, gate or push
was run. All executable checks used `taskset -c 112-127`. No lane edit touched
io_loop.h, wb.h or reorder.cc, so the conditional writeback witness does not apply.

Extractor proof, executed exactly with the permitted CPU affinity:

```sh
taskset -c 112-127 python3 -c "import sys; sys.path.insert(0,'tests'); import gate_ledger_fixture as g; print(len(g.source_labels(open('tests/gate.sh').read())))"
# 484
```

`build/climonfix2/inventory.json` records the source-extracted mainline, missing-call
and fixed inventories. Counter comparisons prove that every mainline label is
retained and these eight labels each occur once in the addition, in BOTH tiers:

| Row declaration | Collection | Added rows |
| --- | --- | ---: |
| `gate.sh:1246`, climon 128-owner delivery mask | ring_unit, line 2852 | 1 |
| `gate.sh:1258`, shutdown policy + signal handoff serverless | climonfix, line 2855 | 1 |
| `gate.sh:1266-1267`, shutdown persistence: 1s/2s x command/sigterm/sigint | climonfix, line 2855 | 6 |

All collection lines precede the quick exit at 2997. This repair restores seven
previously uncollected rows; together with the mask row already visible, the lane
adds eight to mainline. Required owner updates are **EXPECT_QUICK 459 -> 467** and
**EXPECT_FULL 476 -> 484**. The eight corresponding fixture labels are the mask
and policy names above, plus `shutdown persistence (1s, command)`,
`shutdown persistence (1s, sigterm)`, `shutdown persistence (1s, sigint)`,
`shutdown persistence (2s, command)`, `shutdown persistence (2s, sigterm)` and
`shutdown persistence (2s, sigint)`.

Directed positive and negative evidence:

```text
$ taskset -c 112-127 python3 tests/gates_test.py CompleteTierDispatch
Ran 1 test in 1.668s
OK

Throwaway gate source with only collect_job climonfix removed:
AssertionError: 0 != 1 : climonfix shutdown rows must be collected in every correctness tier
Ran 1 test in 0.350s
FAILED (failures=5)
NEGATIVE CONTROL: all five correctness tiers failed at the missing-collection assertion
exit 1
```

The negative runner substitutes only reads of `tests/gate.sh` with
`build/climonfix2/gate-uncollected.sh`, then runs the same CompleteTierDispatch
test. It asserts no errors, exactly five assertion failures, and the named message
in every failure. Evidence: `build/climonfix2/negative-collection.log`.
No checkout file was reverted and no deliberately broken binary was executed.

Every command in the gate's ABBA/receipt self-test row was run, continuing with
independent commands after the receipt refusal so their results remain visible.
`build/climonfix2/checks.json` records commands, return codes and log paths.
Every command below has prefix `taskset -c 112-127 python3`:

| Arguments | Result | Log under `build/climonfix2/` |
| --- | --- | --- |
| `tests/abbagate.py --self-test` | PASS, 135 tests | `abbagate.log` |
| `tests/gate_quiet.py --self-test` | PASS, 8 tests | `quiet.log` |
| `tests/gate_measurements.py --self-test` | PASS, 11 tests | `measurements.log` |
| `tests/gate_receipt.py --self-test` | FAIL, fixture guard before receipt controls | `receipt.log` |
| `tests/abba_instrument.py --self-test` | PASS, 7 tests | `instrument.log` |
| `tests/background_environment_test.py` | PASS, 11 tests | `background.log` |
| `tests/gate_history.py self-test` | PASS, 55 tests | `history.log` |
| `tests/gate_process_test.py` | PASS, 12 tests | `process.log` |
| `tests/gates_test.py` | PASS, 58 tests, including TSANWiring and collection regression | `gates.log` |
| `tests/tailgen_stall.py --self-test` | PASS, 3 tests | `tailgen.log` |

Thus 300 tests pass across the independent commands, but this is NOT a passing
receipt-chain result. The literal requested `tests/gates_test.py serverless` was
also attempted and exits 1: `AttributeError: module '__main__' has no attribute
'serverless'` (`gates-serverless-selector.log`). This script uses unittest test
selectors; no positional selector is needed to run its complete serverless suite.
No runner behavior was changed to hide that invocation error.

The receipt refusal is exact and actionable:

```text
RECEIPT FIXTURE REFUSED: tests/fixtures/nullrefresh-ledger-labels.json: EXPECT_FULL=476, fixture=476, source declarations=484
Missing fixture labels: 'climon 128-owner delivery mask' (x1); 'shutdown persistence (1s, command)' (x1); 'shutdown persistence (1s, sigint)' (x1); 'shutdown persistence (1s, sigterm)' (x1); 'shutdown persistence (2s, command)' (x1); 'shutdown persistence (2s, sigint)' (x1); 'shutdown persistence (2s, sigterm)' (x1); 'shutdown policy + signal handoff serverless' (x1)
Extra fixture labels: none
```

`gate_ledger_fixture.check` requires source declarations, fixture labels and
EXPECT_FULL to agree; `gate_receipt.self_test` invokes that guard before setting up
any receipt controls. A green receipt is impossible with both protected inputs
frozen at 476. The lane leaves this refusal intact and does not relax the checker,
patch its inputs or regenerate the fixture. Mainline must review/synchronize the
eight labels and the counts before rerunning the receipt command above.

`taskset -c 112-127 bash -n tests/gate.sh` and `git diff --check` pass.
After the owner synchronization and receipt rerun, the mainline live gate command
is `tests/gate.sh iteration`; it now collects all eight rows. Standalone restart
and >64-owner commands, negative controls and the original 14-cell measurement
request remain in `MEASURE-REQUEST-climonfix.md`. This follow-up claims no live
recovery, delivery or performance result.

`git diff b997807081b47bb0a5708f832dcf26963e2d9bd2 --stat` (includes the merge and this report):

```text
 MEASURE-REQUEST-climonfix2.md                 | 159 ++++++++++++++
 MEASURE-REQUEST-flushfix.md                   | 275 ++++++++++++++++++++++++
 MEASURE-REQUEST-ktlsfix.md                    | 244 +++++++++++++++++++++
 Makefile                                      |  37 +++-
 docs/CONFIGURATION.md                         |  29 ++-
 src/cmd/multidb.cc                            |  34 ++-
 src/cmd/t_server.cc                           |  17 +-
 src/net/tls.cc                                | 142 +++++++++----
 src/net/tls.h                                 |  15 +-
 tests/fixtures/nullrefresh-ledger-labels.json |  31 ++-
 tests/flushfix_checks.py                      | 198 +++++++++++++++++
 tests/flushfix_unit.cc                        | 211 ++++++++++++++++++
 tests/gate.sh                                 |  56 ++++-
 tests/gate_measurements.json                  |   8 +-
 tests/gates_test.py                           |   2 +
 tests/ktls_keyupdate.cc                       |  90 ++++++--
 tests/ktls_keyupdate_unit.cc                  | 294 ++++++++++++++++++++++++++
 tests/kvobj_header_unit.cc                    | 113 ++++++++++
 tests/tls.py                                  |  28 +--
 19 files changed, 1874 insertions(+), 109 deletions(-)
```
