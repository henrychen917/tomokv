# T5 generated-script argv limit — gatesfix

2026-10-03. Worktree `/home/user/Projects/cx-gatesfix`, branch `cx-gatesfix`.
Fetched and merged `origin/cpp` first: already current at `b47544aad`.
Implementation commit: `0be192e3b`.

This is a serverless harness repair. No performance measurement or PAD arm is
requested. No server, benchmark, or gate was run. All proof commands were pinned
to CPUs 112-127. Nothing was pushed.

The scheduler's assembled Bash program reached **130,614 bytes** across the
existing scenarios: only 457 more bytes fit before the terminating NUL hits
Linux's 131,072-byte single-argument limit. Adding gate rows therefore made
`execve(timeout, ...)` fail with `E2BIG` before Bash or the scheduler started.

`SchedulerWiring._run_scheduler` now writes that same program to `scheduler.sh`
inside its existing `TemporaryDirectory` and invokes `bash <path>`. The working
directory, environment, CPU selection, `timeout --kill-after=2 45`, Python's
50-second timeout, assertions, and failure-artifact script text are unchanged.
The optional `_gate_path` argument and returned byte count support the new
regression control; normal callers still read the worktree's `tests/gate.sh`.

The new test inserts exactly 65,536 bytes of comment lines immediately after the
unique top-level `WORKER_PIDS=()` line in a disposable gate copy. This puts the
padding inside the actual extracted scheduler slice. It requires an assembled
program larger than 128 KiB, a clean verdict, and every canonical job completed.
The normal-tree control assembles **194,664 bytes**. It cannot pass by appending
padding outside the slice or by skipping execution.

The negative-control copy restores only `'bash', '-c', script` at the launch
site, retaining the new test. Running
`python3 tests/gates_test.py SchedulerWiring.test_large_gate_script_avoids_single_argument_limit`
there exits 1 with one error:

```text
OSError: [Errno 7] Argument list too long: 'timeout'
Ran 1 test in 112.268s
FAILED (errors=1)
```

Proof results (all serverless):

| Command | Worktree | Copy with gate.sh +20 KiB |
| --- | --- | --- |
| `python3 tests/gates_test.py` | PASS, 58 tests | PASS, 58 tests |
| `python3 tests/abbagate.py --self-test` | PASS | PASS |
| `python3 tests/gate_quiet.py --self-test` | PASS, 8 tests | PASS, 8 tests |
| `python3 tests/gate_measurements.py --self-test` | PASS, 11 tests | PASS, 11 tests |
| `python3 tests/gate_receipt.py --self-test` | PASS, including nested controls | PASS, including nested controls |
| `python3 tests/abba_instrument.py --self-test` | PASS, 7 tests | PASS, 7 tests |
| `python3 tests/background_environment_test.py` | PASS, 11 tests | PASS, 11 tests |

The padded copy is an archive of the committed tree with exactly 20,480 comment
bytes inserted at the same scheduler marker: gate.sh grows from 168,324 to
188,804 bytes. Its ordinary scheduler scenarios reach **151,094 bytes**; its
additional 64 KiB regression reaches **215,144 bytes**. The padded harness run
used a transparent `runpy` wrapper with a subprocess audit hook to record script
sizes; it changed no subprocess arguments or test assertions. Both receipt
chains use the listed entry points directly, in order, and stop on any failure.

## Other call sites

Searched `tests/` and `tools/` with `grep`, including `-c`, `-uc`, literal
`bash -c` / `python3 -c`, `sys.executable`, and `shell=True`. The following are
maximum UTF-8 program lengths over the checked-in fixture cases, excluding the
terminating NUL. Source lines refer to this commit. The scheduler is the only
payload that crosses 128 KiB with the requested growth; no additional launch
sites require conversion. The largest remaining payload is 18,415 bytes, still
below 128 KiB even with both 64 KiB and 20 KiB added to that payload.

| Site | Generated program | Maximum bytes |
| --- | --- | ---: |
| `tests/gates_test.py:313` | row-budget helpers + stub | 11,037 |
| `tests/gates_test.py:406` | feature/performance ledger wiring | 5,585 |
| `tests/gates_test.py:471` | multi-DB job + stub | 2,096 |
| `tests/gates_test.py:523` | quietcheck script + stub | 2,290 |
| `tests/gates_test.py:559` | NIC ownership cleanup + body | 602 |
| `tests/gates_test.py:662` | ABBA termination cleanup + launch | 2,890 |
| `tests/gates_test.py:757` | worker collector + ledger fixture | 2,620 |
| `tests/gates_test.py:841` | affinity probe + response stub | 934 |
| `tests/gates_test.py:880` | canonical quick/full collector inventory | 5,515 |
| `tests/gates_test.py:1143` | scheduler, converted to a file | 130,614; 215,144 with both pads |
| `tests/gates_test.py:1443` | TSAN helpers + job body | 5,618 |
| `tests/gates_test.py:1507` | TSAN build bodies + stub | 1,307 |
| `tests/gates_test.py:1596` | full coordinator + plan + stub | 18,415 |
| `tests/gates_test.py:1627` | coordinator missing-join negative control | 18,406 |
| `tests/gates_test.py:1655` | performance candidate dispatch + stub | 1,354 |
| `tests/gates_test.py:1697` | early gate dispatch + stub | 381 |
| `tests/gate_history.py:1060` | watcher shell fixture | 248 |
| `tests/gate_history.py:1191` | row helpers + optional functions + body | 13,238 |
| `tests/gate_history.py:1134` | bounded-shell execution of the preceding assembly | 11,767 |
| `tests/gate_history.py:1441` | real-job helpers + cleanup + finalizer + stub | 15,856 |
| `tests/gate_history.py:1488` | recovery function + ledger fixture | 1,193 |
| `tests/gate_history.py:1530` | ABBA timeout helpers + cleanup + body | 13,051 |
| `tests/gate_history.py:1562` | inherited-root cleanup + body | 2,080 |
| `tests/differ_fanout_test.py:146` | differ_gate.sh + workload stubs | 16,645 |
| `tests/differ_fanout_test.py:389` | differential collector + ledger stub | 2,393 |
| `tests/gateplan.py:371` | shell plan + argv printer | 3,080 |
| `tests/tailgen_stall.py:166` | gate row + workload stubs | 1,413 |
| `tests/load_calibration.py:518` | strict campaign shell fixture | 174 |

The other Python fixture programs are fixed text, except one interpolated
temporary pathname. Their sizes were checked directly from their constructions:

| Site | Maximum program bytes |
| --- | ---: |
| `tests/gate_history.py:979` | 300 |
| `tests/gate_history.py:1001` | 266 |
| `tests/gate_history.py:1077` nested child | 114 |
| `tests/gate_history.py:1219` nested child | 20 |
| `tests/gate_history.py:1281` nested child | 19 |
| `tests/gate_history.py:1307` nested child | 163 |
| `tests/gate_history.py:1433` nested child | 176 |
| `tests/abba_worker_affinity.py:332` | 473 |
| `tests/abba_aslr.py:464` | 55 |
| `tests/mutants.py:808` nested child | 122 |
| `tests/mutants.py:810` | 54 |
| `tests/mutants.py:815` | 321 |
| `tests/mutants.py:837` | 160 |
| `tests/abbagate.py:4374` | 328 here; 361 in the longer padded-copy path |
| `tests/abbagate.py:4404` | 255 |
| `tests/gates_test.py:564,578,579,638,661` | 27 each |
| `tests/gate_history.py:1075,1439` | 27 each |
| `tests/abbagate.py:4350,4352,4364,4371` | 27 each |

The remaining grep hits in `matrix.sh`, `xshard_dispatch_scale.sh`, and
`writer_atomic_campaign.py` are configuration/CPU expansion or fixed activity
probes, with no embedded gate slices, fixture data, or ledgers. Compiler `-c`
and taskset `-c` matches are unrelated. No qualifying site exists in `tools/`.
Existing stdin-fed Bash fixtures in `abbagate.py` and `gate_receipt.py` already
avoid this limit.

The size audit also executed these serverless suites successfully:
`gate_history.py --self-test` (55 tests), `differ_fanout_test.py` (18),
`gateplan.py --self-test` (11), and `tailgen_stall.py --self-test` (3).

Logs, the audit wrapper/JSON size inventories, the old-code control, and the
padded copy remain under `build/gatesfix-proof/`. Reproduction launchers are
`proof-tree.sh`, `proof-padded.sh`, and `audit-other.sh`; invoke them with
`taskset -c 112-127 bash` from this worktree. The old-code copy is under
`build/gatesfix-proof/old-code/`.

No gate row was added or retired. `tests/gate.sh`, `EXPECT_QUICK=447`,
`EXPECT_FULL=464`, and the label fixture are unchanged.
