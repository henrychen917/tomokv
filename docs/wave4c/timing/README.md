# ABBA correctness-row timing

All 15 original suite commands passed on `0d9950d7b` production/test sources, with the committed 685/702 EXPECT and label fixture. The serial timing pass inherited CPUs 64–111 and had no concurrent builds or server workloads from this lane. `before/suites.json` records exact commands and return codes; each suite JSON records unittest-case wall times, including in-process nested suites. Child-suite aggregate timings also remain in the raw logs. Procedural controls retain their original PASS output.

| Suite | Seconds | Status |
|---|---:|---|
| `tests/abbagate.py` | 285.696 | PASS |
| `tests/gate_quiet.py` | 0.102 | PASS |
| `tests/gate_measurements.py` | 2.689 | PASS |
| `tests/gate_receipt.py` | 130.491 | PASS |
| `tests/abba_instrument.py` | 1.298 | PASS |
| `tests/background_environment_test.py` | 0.058 | PASS |
| `tests/gate_history.py` | 21.487 | PASS |
| `tests/gate_process_test.py` | 0.541 | PASS |
| `tests/gates_test.py` | 97.056 | PASS |
| `tests/gate_subset_test.py` | 0.117 | PASS |
| `tests/wb_policy.py` | 0.056 | PASS |
| `tests/lb_stationary.py` | 0.219 | PASS |
| `tests/netio.py` | 0.051 | PASS |
| `tests/gateprod.py` | 1.944 | PASS |
| `tests/tailgen_stall.py` | 0.091 | PASS |

Sum of component process runtimes: **541.896 seconds**.

The exhaustive dry-run test takes **1.6768 s**, or 0.31% of this row. It still checks all **64 cells × 2 arms = 128** server argv pairs and every load argv. `git diff 8656f9fa9 -- tests/gateprod.py tests/headline_cells.txt tests/netio_cells.txt` is empty: no wave-4 lane added a cell or arm. Work scales with the product: the separate cProfile receipt observes 128 calls to `Runner.measure` and 320 calls to `load_layout` (64 dry-plan layouts + 128 instrument layouts + 128 independently constructed expected load layouts). There is also fixed work from two instrument fingerprints. The profiled test takes 3.266 s due to profiler overhead; the unprofiled 1.6768 s is the runtime measurement. No candidate or load generator is started by this intercepted-argv control.

The large tests are `abbagate.test_real_null_collection_comparison_and_subset_controls` (114.0506 s) and `gates_test.SchedulerWiring.test_completion_is_not_visible_before_its_record_is_written` (62.0406 s). In the failed landing receipt, `abbagate.py` took 294.072 s, `gates_test.py` took 440.475 s, and the row exhausted 900 s during the argv test. Thus the timeout location does not identify the expensive test. The owner supplied the previous cx-compat2 landing row runtime of **851.44 s**; that measurement is used as the completed landing-runtime basis.

**Harness change:** the existing `row_begin` special-case block now assigns **1200 s** to this exact row and records `ROW_BASIS=abba-selftest-cx-compat2-851.44s-plus-40pct-rounded`. Calculation: 851.44 × 1.40 = 1192.016 s, rounded up to the next minute, 1200 s (40.94% actual margin). This also gives 300 s above the observed incomplete 900 s run. A longer fixed budget accounts for the observed landing scheduling spread; no assertion, cell, arm, row, EXPECT value or fixture is removed or relaxed. The wiring control now checks this budget and its basis for ordinary history, explicit plans and no-history inputs, and retains the original expectations for every other row.

The final gate-owned `abba_selftest` passed in **636.54 s** with the explicit
1200 s budget and recorded basis, using a fresh private history path. Its
`gates_test.py` suite took 186.826 s; the entire `gateprod.py` suite took 1.833 s.
All 15 suite commands passed, with the committed landing EXPECT/fixture state.
The exact command, ledger and archived original output are in
[../../wave4/proof/wave4c-abba](../../wave4/proof/wave4c-abba). The separate
required `python3 tests/gates_test.py` invocation passed **67/67**, taking
184.869 s wall time (184.768 s reported by unittest); its receipt is in
[../../wave4/proof/wave4c-gates-test](../../wave4/proof/wave4c-gates-test).
