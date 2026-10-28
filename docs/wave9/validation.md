# Wave9 correctness evidence

All live runs use the gate’s whole-job interface. The per-invocation map is [coverage.json](coverage.json); each receipt records argv, environment, source/binary hashes, every declared leg and its finalizer. Raw logs and verdicts are retained in [job-evidence](job-evidence), with SHA-256s and per-file manifests indexed by [job-evidence-index.json](job-evidence-index.json).

These are overlapping partial-job campaigns, not a full landing gate. Do not add their public row totals to infer the 881/898 landing count.

Requested whole-job invocations: **{'PASS': 219, 'FAIL': 2}**. Added labels with passing frozen-POST evidence: **74/74**.

| Attempt | Exit | Public rows (ok / FAIL) | Disposition |
| --- | ---: | ---: | --- |
| [atomic-recheck2](jobs/atomic-recheck2.json) | 0 | 29 / 0 | Complete atomic_units and at412-owner after fixture repair. |
| [execfair-loaded](jobs/execfair-loaded.json) | 0 | 2 / 0 | All eight mode/atomic/engine legs; four finite CPU burners share the server allocation. |
| [final-additional](jobs/final-additional.json) | 0 | 59 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-differ-epoll](jobs/final-differ-epoll.json) | 0 | 6 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-differ-uring](jobs/final-differ-uring.json) | 0 | 6 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-engine-epoll](jobs/final-engine-epoll.json) | 0 | 191 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-engine-uring](jobs/final-engine-uring.json) | 0 | 191 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-mode-epoll-1s](jobs/final-mode-epoll-1s.json) | 0 | 59 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-mode-epoll-2s](jobs/final-mode-epoll-2s.json) | 0 | 59 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-mode-uring-1s](jobs/final-mode-uring-1s.json) | 0 | 59 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-mode-uring-2s](jobs/final-mode-uring-2s.json) | 0 | 59 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-once](jobs/final-once.json) | 1 | 271 / 4 | R7 affinity, T12 claim arming, exbatch negative-control diagnostic and obsolete APPLY-window fixture; each repaired and rechecked as a whole job. |
| [final-persistence-1s](jobs/final-persistence-1s.json) | 0 | 141 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-persistence-2s](jobs/final-persistence-2s.json) | 0 | 141 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [final-selftest](jobs/final-selftest.json) | 2 | no rows | Setup rejected a 14-core allocation before any job; minimum is 16 physical CPUs. |
| [final-selftest2](jobs/final-selftest2.json) | 1 | 0 / 1 | Incomplete throwaway source copy lacked tracked measurement fixture documents; copy completed. |
| [final-selftest3](jobs/final-selftest3.json) | 1 | 0 / 1 | Complete one-slot scheduler fixture exceeded 45s beside independent parallel fixtures; deadline and inventory preserved, serial fixture moved first. |
| [final-selftest4](jobs/final-selftest4.json) | 0 | 1 / 0 | Complete ABBA selftest after scheduler fixture sequencing repair; throwaway EXPECT 881/898 only. |
| [final-tcl](jobs/final-tcl.json) | 1 | 3 / 3 | XGROUP statistics in both modes, one cross-connection WATCH ordering assertion in 1s; native compat2 legs run, its dependency verdict remains red. |
| [integration-first](jobs/integration-first.json) | 0 | 2 / 0 | Pre-budget integration check; final POST rechecked normally and loaded. |
| [lane-rows](jobs/lane-rows.json) | 1 | 49 / 7 | Four stale wound-hook anchors and three transient RESET boot failures during relinking; all rechecked on frozen POST. |
| [repair-rechecks](jobs/repair-rechecks.json) | 1 | 35 / 1 | Atomic fixture initially omitted split inbox initialization; complete atomic/owner recheck passes. |
| [supplemental-once](jobs/supplemental-once.json) | 0 | 27 / 0 | Whole declared job set, frozen POST; inspect the receipt for its modes/engines. |
| [tcl-first](jobs/tcl-first.json) | 1 | 1 / 2 | Both modes expose the mandatory XGROUP DESTROY INFO-statistics dependency. |
| [tcl-planted](jobs/tcl-planted.json) | 1 | 3 / 3 | Expected negative control: POST passes 64 GEO assertions; planted arm adds 16 mandatory GEO failures in each mode. |

The planted Tcl arm is deliberately broken and is never a passing candidate. Original failed attempts remain in this table after successful repairs.

Standalone controls: `tests/gates_test.py` passes 73/73 after the sequencing repair ([receipt](gates-test-serialized-final.json)); the earlier separate quiet run also passed. An intermediate launch was interrupted before its socket check because its required `GATE_TEST_PORT=20098` override was omitted; it is not counted as a completed test. Lottery’s runner and evidence controls each pass 17/17; both copied witness binaries built. `make all` succeeded and all 55 recorded `make -q` checks returned zero ([freshness](build-freshness.json)).

**NOT RUN:** throughput benchmarks, the 28-cell wave null, fixed-anchor race, contended-script performance storm and full `tests/gate.sh iteration` remain maintainer-owned. Lottery has no `gate.sh` job: its copied release/ASAN builds and serverless controls were exercised; its independent K=20 nightly campaign was not run. The parked layout-placement and pipelined stream-removal diagnostics were not added to the gate or represented as passing runs; their lane evidence is linked in [diagnostics.md](diagnostics.md).
