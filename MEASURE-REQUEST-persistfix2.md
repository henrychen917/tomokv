**persistfix2 — gate integration repaired; receipt metadata synchronization required.**

Worktree/branch: `/home/user/Projects/cx-persistfix`, `cx-persistfix`.
Launch HEAD: `ea03c56ca026d852890b0b39e5758ed511201d8b`.
First operation after checking the worktree: `git fetch origin cpp && git merge --no-edit origin/cpp`.
Merged mainline: `068fdb816`; merge commit: `406c834b2`.
Repair commit: `c5fe69bde`.

No persistfix2 implementation changes under `src/`: `git diff 406c834b2 -- src/` is empty.
The required merge imported mainline's source changes; the repair changes only three test files.
The PS1/PS2/PS14 implementation, AOF format, layout locks and prior null GO are unchanged by this repair.
No new measurement or PAD arm is requested. No build, server binary, load generator, benchmark,
live recovery test or gate was run. All executed checks ran under `taskset -c 112-127`.
Nothing was pushed.

**Diagnosis and fix.**

* The supplied live log proves `EADDRINUSE` at the plain bind in the driver; it does not identify a
  live socket owner. The launch source already calls `stop` at `tests/gate.sh:2165` before the first
  live row at `:2172`. After the merge those boundaries are `:2207` and `:2216`.
  `stop` (`:724`) signals and reaps the owned server, clears `SRV`, and settles the port. A plain
  Python bind nevertheless rejects a server port whose accepted connections remain in TIME_WAIT.
  A deterministic socket-only regression reproduces that failure without a server process.
* `tests/persistfix.py:70` now gives the guard `SO_REUSEADDR`, matching the server's restart semantics.
  It deliberately does not set `SO_REUSEPORT`: a live listener still produces `EADDRINUSE`.
  The existing gate stop/driver/reboot sequence remains intact. Each driver still owns its child PID,
  both boots and fresh data under `$TMPDIR/persistfix`; the following everysec boot at
  `tests/gate.sh:2233` takes the allocated port back after all four invocations exit.
* `tests/gate.sh:1247` moves the existing serverless persistence row into `job_persistfix_units`.
  Registration is at `:983`, the `production_units` prerequisite at `:2796`, and collection at
  `:2857`. The merged unit build and readiness lists at `:2733,2736` retain `persistfix-units`
  together with netcap, flushfix, ktls and splitlocal targets. The entire `job_core_units` body
  is byte-identical to `origin/cpp`; its exact TSAN row lists are unchanged.
* `tests/gates_test.py:1390` adds three serverless regressions to the existing receipt row:
  port reuse plus refusal of a live listener; all eight real gate invocations receiving a reaped
  slot with the correct geometry and private artifact directory; and the separate unit job's
  dependency, failed-build and failed-check outcomes. The gate snippets use stubs for every server
  and workload boundary. The socket fixture uses one ephemeral loopback pair, with no server process.

**Directed proof and negative controls.**

Before moving the row, the actual merged gate reproduces the reported failures:

```text
$ taskset -c 112-127 python3 -B tests/gates_test.py TSANWiring
Ran 5 tests in 0.538s
FAILED (failures=12)
```

The named failures are `test_core_rows_execute_both_matching_controls`,
`test_core_runtime_report_unavailability_and_missing_witness_all_fail`, and
`test_topology_rows_require_ready_success_and_exact_witness`, including their subtests.
Log: `build/persistfix2/old-core.log`.

A throwaway copy at `build/persistfix2/old-bind.py` removes only the new `setsockopt` line,
restoring the old guard's bind behavior. Loading that copy as `persistfix` and running
`PersistfixWiring.test_driver_reuses_stopped_port_but_refuses_live_listener` exits 1:

```text
AssertionError: stopped gate port must be reusable after TIME_WAIT: [Errno 98] Address already in use
Ran 1 test in 0.002s
FAILED (failures=1)
```

Log: `build/persistfix2/old-bind.log`. The positive test first requires that a plain bind fails in
the same TIME_WAIT window; it cannot pass by missing the window. It also requires the repaired
guard to reject a live listener. No production data or server binary is involved.

After the repair:

```text
$ taskset -c 112-127 python3 -B tests/gates_test.py PersistfixWiring TSANWiring
Ran 8 tests in 0.161s
OK
```

Log: `build/persistfix2/wiring.log`. `taskset -c 112-127 bash -n tests/gate.sh` and
`git diff --check` also pass.

**Receipt chain — the metadata refusal is not waived.**

The entire current `job_abba_selftest` chain was attempted, including its three additional
checks beyond the addendum's seven named commands. Each command ran with `taskset -c 112-127`.
Logs are `build/persistfix2/<name>.log`; statuses and timings are in
`build/persistfix2/receipt-results.json`.

| Command after `taskset -c 112-127 python3 -B` | Result |
|---|---|
| `tests/abbagate.py --self-test` | PASS; 100 + 10 + 9 + 16 tests |
| `tests/gate_quiet.py --self-test` | PASS; 8 tests |
| `tests/gate_measurements.py --self-test` | PASS; 11 tests |
| `tests/gate_receipt.py --self-test` | REFUSED before its tests; fixture/count drift below |
| `tests/abba_instrument.py --self-test` | PASS; 7 tests |
| `tests/background_environment_test.py` | PASS; 11 tests |
| `tests/gate_history.py self-test` | PASS; 55 tests |
| `tests/gate_process_test.py` | PASS; 12 tests |
| `tests/gates_test.py` | PASS; all 61 tests, including scheduler and TSAN wiring |
| `tests/tailgen_stall.py --self-test` | PASS; 3 tests |

Nine suites / 303 tests pass. **The complete chain is not green.**
`tests/gate_receipt.py:803` rejects the unchanged mainline metadata:

```text
RECEIPT FIXTURE REFUSED: tests/fixtures/nullrefresh-ledger-labels.json:
EXPECT_FULL=476, fixture=476, source declarations=485
```

The addendum explicitly says not to edit `EXPECT_*` or the label fixture, so the merge retains
mainline's 459/476 and its exact fixture bytes. No checker or assertion was weakened. Mainline
must synchronize the metadata (or explicitly authorize that synchronization) before this command
can pass in this tree. An asynchronous clarification was requested after the repair was committed.

**Gate arithmetic, by collection line.**

The moved serverless row is collected at `tests/gate.sh:2857`; the two AOF engine jobs are collected
at `:2945`. Both precede the quick-tier exit at `:2999`. The latter contribute
2 engines × 2 modes × 2 cases = 8 rows. The original persistfix delta remains **+9 quick / +9 full**;
persistfix2 adds **0 / 0**. Three new Python unittest cases run inside the existing receipt row.

On the merged mainline baseline, the required totals are **468 quick / 485 full**
(459/476 + 9/9). `gate_ledger_fixture.source_labels` independently enumerates these totals from
the source declarations; evidence is in `build/persistfix2/row-inventory.json`.
Mainline's fixture needs the nine persistence labels and both occurrences of
`AOF always acknowledged-prefix recovery` renamed to
`AOF always recovery after quiescent SIGKILL`. The renames add no rows.

**Exact mainline live checks — not executed here.**

After mainline synchronizes the count/fixture, rerun the receipt commands in the table above.
For the live recovery matrix, use a quiet mainline allocation and an unowned port; the driver
checks the port and creates fresh data for every invocation:

```sh
cd /home/user/Projects/cx-persistfix
taskset -c 112-127 make -j16 all persistfix-units persistfix-live-controls
taskset -c 112-127 python3 -B tests/persistfix_checks.py
for engine in epoll uring; do
  for mode in 2s 1s; do
    for check in kill term; do
      python3 tests/persistfix.py --binary build/tomokv \
        --mode "$mode" --case "$check" --net-io "$engine" \
        --cores 0-7 --ratio 6:2 --port 16379 --count 1024 \
        --artifacts build/persistfix2-live || exit 1
    done
  done
done
tests/gate.sh iteration
```

The full gate additionally verifies reuse after the preceding AOF server has stopped, using its
allocated `$PORT` and job-private `$TMPDIR`. Re-run the original live negative controls only on
disposable data; these must fail at the named assertions, not at the port guard:

```sh
python3 tests/persistfix.py --binary build/persistfix-controls/old-ack/tomokv \
  --mode 2s --case kill --net-io uring --cores 0-7 --ratio 6:2 --port 16379 \
  --artifacts build/persistfix2-old-ack
# Required failure: acknowledged/executed write lost on reload: persistfix:window:<attempt>
# Required server witness: AOF ack-window: SIGKILL before post

python3 tests/persistfix.py --binary build/persistfix-controls/old-close/tomokv \
  --mode 2s --case term --net-io uring --cores 0-7 --ratio 6:2 --port 16379 \
  --artifacts build/persistfix2-old-close
# Required failure: persistence shutdown must drain, with refusal/backlog evidence.
```

**Diff from launch HEAD.**

The following includes the required mainline merge. The repair alone is
`git diff 406c834b2 c5fe69bde --stat`: three test files, 121 insertions, 5 deletions.
The report is committed separately.

```text
 MEASURE-REQUEST-flushfix.md                   | 275 ++++++++++++++++++++++++
 MEASURE-REQUEST-ktlsfix.md                    | 244 +++++++++++++++++++++
 MEASURE-REQUEST-netcap.md                     | 281 ++++++++++++++++++++++++
 MEASURE-REQUEST-persistfix2.md                | 209 ++++++++++++++++++
 Makefile                                      |  41 +++-
 docs/CONFIGURATION.md                         |  29 +++
 src/cmd/multi.h                               |   1 +
 src/cmd/multi.inc                             |  25 ++-
 src/cmd/multidb.cc                            |  34 ++-
 src/cmd/t_server.cc                           |  31 ++-
 src/core/config.h                             |  37 +++-
 src/core/io_loop.h                            |  41 +++-
 src/core/live_config.h                        |   6 +-
 src/core/reorder.cc                           |  20 +-
 src/core/server.h                             |   8 +
 src/net/conn.h                                |  39 +++-
 src/net/resp.h                                |  84 +++++---
 src/net/tls.cc                                | 142 +++++++++----
 src/net/tls.h                                 |  15 +-
 tests/fixtures/nullrefresh-ledger-labels.json |  68 +++---
 tests/flushfix_checks.py                      | 198 +++++++++++++++++
 tests/flushfix_unit.cc                        | 211 ++++++++++++++++++
 tests/gate.sh                                 | 101 +++++++--
 tests/gate_measurements.json                  |   8 +-
 tests/gates_test.py                           | 101 +++++++++
 tests/knobs.py                                |  34 +++
 tests/ktls_keyupdate.cc                       |  90 ++++++--
 tests/ktls_keyupdate_unit.cc                  | 294 ++++++++++++++++++++++++++
 tests/kvobj_header_unit.cc                    | 113 ++++++++++
 tests/netcap.py                               | 185 ++++++++++++++++
 tests/netcap_unit.cc                          | 262 +++++++++++++++++++++++
 tests/persistfix.py                           |  12 +-
 tests/tls.py                                  |  28 +--
 tomokv.conf                                   |   4 +
 34 files changed, 3076 insertions(+), 195 deletions(-)
```
