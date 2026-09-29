TomoKV rltopo2 gate bookkeeping repair, 2026-09-29

The four reported gating failures are addressed by `14a9e1dd3d6b88fe636d695b367a648fdc397d35` (Fix topology gate witnesses and row bookkeeping). The requested prerequisite `9c4717da0` was merged first as `c34c812fc779c1546efbedcb19e9f5263f38ac40`, without conflicts. The repair itself changes only `tests/gate.sh` and `tests/gates_test.py`; the prerequisite merge imports mainline's existing execfix changes.

All builds and serverless tests stayed on CPUs 112-127. No server, benchmark, load generator, gate, or push was run. No further performance measurement or PAD arm is requested for these bookkeeping changes.

**Causes and fixes.** Source references below describe the repaired tree; the original failing gate lines retain the same numbers. Saved mainline evidence is under `build/gate-run.4DxMAx/`.

| Reported FAIL | Cause and evidence | Fix in `14a9e1dd3` |
| --- | --- | --- |
| read-local topology demotion (1s) | The third conjunct at `tests/gate.sh:1267` invoked `rg`, unavailable on the gate's non-interactive PATH. `build/gate-run.4DxMAx/jobs/core_units/output.log:16` records `rg: command not found`; `jobs/core_units/gate-rltopo-1s.txt:32` contains the exact expected PASS line. | Replace `rg -Fxq` with `grep -Fxq`, preserving fixed-string, whole-line matching and both preceding success requirements. |
| read-local topology demotion (2s) | The same third conjunct failed. `build/gate-run.4DxMAx/jobs/core_units/output.log:19` records the missing command; `jobs/core_units/gate-rltopo-2s.txt:32` contains the exact expected PASS line. | The shared loop uses `grep -Fxq` for both modes. |
| ABBA comparison + saturation negative controls | `tests/gate.sh:2375` runs `tests/gates_test.py`. Its `TSANWiring` fixture extracts the whole `core_units` job, now seven core rows plus two topology rows, but the original assertions at lines 1357, 1359, 1365 and 1369 assumed seven rows/calls. Its unit stub also emitted no topology PASS witness. The saved self-test log reports seven assertion failures, including subtests. | Update the positive rows/call inventory at `tests/gates_test.py:1367`, the all-failure expectations to nine at `tests/gates_test.py:1380` and `tests/gates_test.py:1384`, and the stub to model topology evidence independently. The all-failure cases explicitly omit the topology witnesses. |
| PROGRAM-STATE ledger (461/459 checks) | `tests/gate.sh:261` still expected 459 after the two topology rows were added. `program_state` compares the count at `tests/gate.sh:490`, called for full/iteration at line 3089. The saved ledger has 462 entries: 461 checked rows plus the ledger's own failure entry. | Set the explicitly authorized `EXPECT_FULL` to 461. The existing optional NIC adjustment remains intact. |

The gate **built and executed both demotion witnesses**. Registration already exists in the production build command at `tests/gate.sh:2600`, the readiness-marker loop at line 2603, and the `core_units` dependency at line 2660. The saved `unit-ready/rltopo-unit` marker exists. The saved `jobs/production_units/build.log:147` compiles the unit and line 153 links it; that build log is 68,420 bytes, while its sibling `output.log` is empty. The two unit PASS lines match byte for byte, including `arm transients`. The failure occurred during verdict collection after execution.

Codex's injected tools PATH contains a ripgrep binary, but a clean non-interactive system PATH reproduces exit 127 and `rg: command not found`. The fixture now deliberately makes `rg` unavailable (`tests/gates_test.py:1320`), so that developer-only PATH entry cannot conceal a recurrence. The added serverless control at line 1387 rejects missing readiness, a nonzero unit exit even with a valid PASS line, missing evidence, a wrong mode, and extra trailing text. It adds no gate ledger row.

**Verification.** Logs are retained under `build/rltopo2/`.

| Check | Result / evidence |
| --- | --- |
| Original focused fixture, `taskset -c 112-127 python3 tests/gates_test.py TSANWiring -v` | Reproduced: 4 tests, 7 assertion failures including subtests; `gates-tsan-before.log`. |
| Repaired focused fixture, same command | PASS: 5 tests; `gates-tsan-after.log`. |
| Complete serverless suite, `taskset -c 112-127 python3 tests/gates_test.py -v` | PASS: all 57 tests in 257.011 seconds, exit 0; `gates-test.log`. |
| `taskset -c 112-127 make -j16 build/rltopo-unit` | PASS, rebuilt against the merged source; `build.log`. Subsequent `make -q build/rltopo-unit` returns 0. |
| `ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 taskset -c 112-119 ./build/rltopo-unit 1s` | Exit 0, exact PASS line accepted by `grep -Fxq`, all 15 embedded negative controls caught; `unit-1s.log`. |
| `ASAN_OPTIONS=detect_leaks=1 UBSAN_OPTIONS=halt_on_error=1 taskset -c 120-127 ./build/rltopo-unit 2s` | Exit 0, exact PASS line accepted by `grep -Fxq`, all 15 embedded negative controls caught; `unit-2s.log`. |
| Shell syntax and patch whitespace | `taskset -c 112-127 bash -n tests/gate.sh` and `git diff --check` pass. |
| Saved-ledger count audit | 462 entries minus the failed PROGRAM-STATE entry = 461, matching the repaired full expectation. This reads prior evidence; it does not rerun the gate. |

The unit retains the gate's 16-shard, eight-thread geometry; 2s uses six IO and two executor roles. The rebuilt `build/rltopo-unit` SHA-256 is `3773188493ba5dd519564fdefb790b52bef7dd3aea50016d8cc995eb4e37fb2d`.

**Unchanged server artifact.** `build/tomokv` was neither rebuilt nor relinked; the sanitizer unit uses separate objects. These hashes identify the existing server artifact, not a new server build of the prerequisite merge.

| Artifact | Before | After |
| --- | --- | --- |
| `build/tomokv` SHA-256 | `384feca8664f79f93afcabba570761806b2ae77e6051b3c8abd2a7151920c680` | `384feca8664f79f93afcabba570761806b2ae77e6051b3c8abd2a7151920c680` |

Digest receipts are `build/rltopo2/tomokv-before.sha256` and `build/rltopo2/tomokv-after.sha256`.

**Quick-tier count for the maintainer.** `EXPECT_QUICK` remains 441 under the standing restriction; this task explicitly authorized changing `EXPECT_FULL` only. The two topology rows at `tests/gate.sh:1261` are collected through `core_units` at line 2723, before the quick-tier exit at line 2854. Its corresponding expected count should therefore become **443 = 441 + 2**. Full is now **461 = 459 + 2**. The new Python negative-control test is part of the existing self-test row and does not add another row.

Full/iteration gate acceptance remains for the maintainer. This lane stops after this report.
