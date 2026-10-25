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


## persistfix2

Worktree `/home/user/Projects/cx-persistfix2`, branch `cx-persistfix2`; PRE is `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`. The preceding report is historical. This section describes the final lane. No push or performance measurement was performed.

### Changes and reproduction

| Item | PRE / oracle evidence | Final behavior |
|---|---|---|
| PS4.6 | Every PRE target leg fails; every Redis leg passes | An AOF rewrite leaves LASTSAVE, the RDB save time and save-cron elapsed-time origin unchanged. INFO distinguishes RDB activity from AOF activity; `aof_rewrites` counts attempts at start. |
| PS4.12 | FORCE refusal, modifier parsing, signal configuration and error replies reproduced in both modes/engines | Redis 7.4 modifier grammar and combinations; SAVE/NOSAVE, FORCE, NOW and ABORT; signal-policy CONFIG/boot grammar; exact refusal replies; pending-request cancellation; cancel an active capture before the final save. FORCE permits exit after a failed final save, with no reply and exit status 0. |
| PS4.13 | All three register cases reproduce in every PRE target leg; oracle legs pass | Explicit rewrite with AOF off creates a native base/increment/manifest without ordinary AOF recording. Rewrite and BGSAVE scheduling coalesce and expose the correct state/replies. SAVE coordinates with an active rewrite; invalid BGSAVE options and SAVE failure use the oracle replies. |
| PS4.15 / D8 | Coverage audit finds D8 missing; PRE and the planted control fail every target leg | After an observed AOF write error, write commands and PING receive the exact errno-bearing MISCONF; reads continue. Prequeued write transactions abort with WATCH cleanup; read-only transactions complete. Registered function flags distinguish read-only and writable FCALL/FCALL_RO; legacy EVAL/EVALSHA check nested writes while continuing to serve reads. |

Initial item commits are `f5b1c68be`, `102bfa866`, `41ed3030f`, and `66f4a3c04`. The D8 function correction is `7ad321563`; its stricter acknowledged-write witness is `d9a33d353`; legacy-script admission is corrected in `b6aca6fcd`. Supporting fixture/proof commits follow on this branch.

**NOT REPRODUCED:** NOW alone permitting exit after a failed save. PRE and Redis both refuse it. Exact target geometry: 16 shards; eight fused workers or split 6 IO + 2 executor workers; CPUs 64–71; epoll and io_uring; original directed reproduction port 36800; `--databases 1 --read-local 0 --key-lb 0 --client-lb 0 --flip-auto 0 --appendonly no --save "3600 1"`. A directory occupying the configured `dump.rdb` path causes the final-save failure. NOW bypasses replica waiting, which this single-node architecture does not have. FORCE is the modifier that permits the failed-save exit.

The directed target matrix is 1s/2s × epoll/io_uring, with an oracle assertion leg for each target geometry. The oracle is Redis 7.4.10 at `/home/user/Projects/redis74/src/redis-server`, checked against `/home/user/Projects/redis/src`; `oracle.sha256` records its binary identity. Original reproduction receipts are `docs/persistfix2/pre-{lastsave,shutdown,commands,errors}/`; corresponding corrected receipts and final gate archives retain the wire replies, INFO observations, invocation arguments and exit evidence. The D8 function follow-up was reproduced against the first candidate in all four geometries before correction (`proof/functions-reproduced`); the complete corrected job passes (`proof/functions-corrected`).

D8 arming requires the acknowledged key/value bytes in the increment before lowering RLIMIT_FSIZE to the current file boundary. The next write produces EFBIG deterministically. Both `appendfsync no` and `everysec`, both normal/reorder dispatch paths, and armed fused reads are covered. Required active states must be observed; there are no skipped window assertions. The separate planted control removes only the post-error admission refusal and is never a shipping arm.

The legacy-script correction was reproduced in all four geometries before implementation (`proof/eval-reproduced`). The expanded row checks ordinary and queued EVAL/EVALSHA, unknown SHA replies, protected write errors, reads before a refused write and repeated refused writes. Every final target/oracle leg passes (`proof/eval-corrected`). An initial added Lua PFCOUNT probe encountered an existing native unsupported-command restriction; supported GET and repeated-refused-SET probes replace it, retaining exact oracle assertions. Direct PFCOUNT read availability remains asserted.

### Coverage and row counts

| Finding | Coverage already present before this lane |
|---|---|
| PS4.1 | aoffix2 snapshot, both modes/engines |
| PS4.2 | aoffix2 filename, both modes/engines |
| PS4.3 | aoffix2 large / large_placed, fused and both engines |
| PS4.4 | aoffix2 error, `always`, both modes/engines; D8 `no`/`everysec` refusal added here |
| PS4.5 | tickets, exec_tickets, resurrection, both modes/engines |
| PS4.7 | off-writer acknowledgement, everysec/always, both modes/engines |
| PS4.8 | rewrite_fail2, both modes/engines |
| PS4.9 | manifest_missing, both modes/engines |
| PS4.10 | savefix acknowledged-write recovery after command/SIGTERM, both modes/engines |

The aoffix2 rows are the `job_aof` declarations at `tests/gate.sh:4350`, `:4364` and `:4378`: 32 ordinary case rows + 8 off-writer acknowledgement rows + 4 large-value rows = 44 existing rows. PS4.10 is the eight `shutdown keeps acknowledged writes ($SAVEFIX_MODE, $SAVEFIX_ACTION, $NET_IO)` rows declared at `tests/gate.sh:3390` in `job_snapshot`. Only the D8 `no`/`everysec` policy lacked coverage among the requested PS4.15 findings.

**DQ=+4; DF=+4.** The new collect_job declarations are at lines 5306–5309, before the quick-tier exit at line 5386. Maintainer-owned counts should become **EXPECT_QUICK=772** and **EXPECT_FULL=789**. Neither constant was edited. All 789 explicit fixture labels agree with source declarations, including duplicate occurrences. The raw fixture checker refuses the unchanged 785 count; the prospective in-memory 789 check passes. See `label-inventory.json` and `label-fixture-check.log`.

### Correctness proof

All new/touched gate rows and related battery jobs use `tests/gate.sh`'s own `GATE_ONLY_JOBS` interface, retaining every nested leg. Builds use CPUs 64–79 and `-j16`; ordinary gate servers use 64–71, clients 72–79, ports 36861–36899, 16 shards and split ratio 6:2. Historical rewrite child scripts declare 4:4 on those eight server cores and retain that geometry. Fused reruns use `GATE_TXN_FUSED=1`; shutdown checks include both engine selections.

The isolated PRE proof checkout contains production blobs and Makefile identical to 05a5e01a9, plus current fixtures. Its real build directory resides inside that checkout; a read-only Git object alternate supplies history for existing PAD unit builders. The source identity and private fixture revision are recorded in `pre-proof-source.json`. `final-source-audit.json` rechecks every touched fixture against PRE, all four binary hashes, unchanged owner counts, build freshness and closure of the assigned listener ports.

| Gate invocation | Pass | Fail | Evidence |
|---|---:|---:|---|
| Final POST, complete selected inventory | 400 | 0 | `docs/persistfix2/proof/final-post-regression/` |
| PRE, same selected inventory | 395 | 5 | `docs/persistfix2/proof/pre-regression/` |
| PRE, expanded D8 row | 1 | 1 | `docs/persistfix2/proof/final-pre-errors/` |
| Planted D8 control | 1 | 1 | `docs/persistfix2/proof/final-control-errors/` |
| Final POST, fused persistence | 148 | 0 | `docs/persistfix2/proof/final-post-fused/` |
| PRE, fused persistence | 147 | 1 | `docs/persistfix2/proof/pre-fused/` |
| PRE, final directed fixtures | 1 | 4 | `docs/persistfix2/proof/final-pre-new-rows/` |

The original PRE 400-row selection has 395 passing rows and five expected failures: the four new rows, plus the shutdown-unit assertion that ABORT cancels a pending signal request before save admission. Its six live shutdown legs pass. The PRE fused rerun has 147 passing rows and that same unit failure. All other selected PRE jobs pass. The four new rows' original PRE target legs all fail and all oracle legs pass; the final expanded D8 row is rerun on PRE and the planted control. The final `final-directed-leg-audit.json` checks every nested leg from the retained gate archives: 32 POST legs, 32 PRE legs and eight planted-control legs, including every required D8 durability-window witness.

Reply search evidence is `reply-search.json`. Registered consumers were run: AOF and snapshot jobs on both engines, climonfix, iofix-signal, persistfix_units, router_uniform, dispatch arity/errors, aof_frame, aoforder, both debug jobs, all split/armed feature jobs, both fused jobs, atomic units/batteries, release batteries, CONFIG/scalar/WAITAOF, auth and default-database jobs. `psfix.py`, `shutsave.py` and `redisgap.py` are historical standalone drivers without registered jobs; their complete legacy drivers were NOT RUN. Their relevant registered rows and the serverless harness controls are covered.

Historical rewrite-trigger checks inferred completion from the attempt counter. The fixture now also requires `aof_rewrite_in_progress=0` in all three trigger waits. Retained oracle observations show the counter advancing while the rewrite is active; no success or arming assertion was removed. Three dispatch/router fixtures now use their reserved third port (`port+2`): the former oracle port was occupied by other lanes' outbound TIME_WAIT sockets. Their assertions are unchanged, and all PRE/POST mode/engine legs pass.

Standard differential proof uses the unmodified `tests/differ_gate.sh`, standard seeds **7, 19, 20, 23, 21**, both atomic settings, all declared suites, four MULTI repeats, mode equivalence and armed-read witnesses. PRE and POST matrices run independently on the two eight-core groups inside CPUs 64–79: POST target/oracle 64–71 with clients 72–79 and target/control/oracle ports 36861/36863/36865; PRE reverses the core groups and uses 36881/36883/36885. Exact commands and environment are in `final-proof-invocations.json`.

| Arm / engine / geometry | Pass | Fail | Evidence |
|---|---:|---:|---|
| post-epoll-armed-fused | 466 | 0 | `proof/differ-final-post-epoll-armed-fused/` |
| post-epoll-split | 475 | 0 | `proof/differ-final-post-epoll-split/` |
| post-uring-armed-fused | 466 | 0 | `proof/differ-final-post-uring-armed-fused/` |
| post-uring-split | 475 | 0 | `proof/differ-final-post-uring-split/` |
| pre-epoll-armed-fused | 466 | 0 | `proof/differ-final-pre-epoll-armed-fused/` |
| pre-epoll-split | 475 | 0 | `proof/differ-final-pre-epoll-split/` |
| pre-uring-armed-fused | 466 | 0 | `proof/differ-final-pre-uring-armed-fused/` |
| pre-uring-split | 475 | 0 | `proof/differ-final-pre-uring-split/` |

All eight final PRE/POST matrices pass, including all 80 climon comparison legs. DIFF-TRK-1 was not observed in either PRE or POST epoll armed-fused run. These results provide no evidence that the pre-existing duplicate-invalidation finding is fixed.

| Serverless check | Exit |
|---|---:|
| `python3 tests/gates_test.py` | 0 |
| `python3 tests/psfix_test.py` | 0 |
| `python3 tests/shutsave_test.py` | 0 |
| `python3 tests/differ_test.py` | 0 |
| `python3 tests/aof_frame_order_test.py` | 0 |
| `python3 tests/debug_load_test.py` | 0 |
| `python3 tests/flakeaudit_test.py` | 0 |

Complete serverless output is retained under `docs/persistfix2/proof/final-serverless-*/`.

All final `make -q` checks pass on both PRE and POST: `all`, the 42 executable targets of `job_production_units`, and `mdbqsbr-live-arms` — **44 checks per arm**. See `{pre,post}-build-freshness.json`.

Excluded preliminary attempts are retained as evidence: an initial binary-only REDIS74_ROOT, PRE helper-directory/history assumptions, the three oracle bind failures, and a differential reader-control/oracle port collision. None is counted as a completed proof or as DIFF-TRK-1. The candidate before the legacy-script correction passed its complete 400-row selection (`proof/before-eval-post-regression`). An earlier candidate's completed epoll/split differential matrix passed 475/475; final results above use the final candidate SHA.

### Identity, layout and limits

The unchanged object normalizer compares all **110 production-linked objects**, **18,338 function pairs**, **477 changed bodies** and **92 inventory additions/removals**. Every changed object body and inventory addition/removal has a reason in `identity/object-changed-bodies.md`; unit instrumentation copies are excluded from that production inventory. The strict linked normalizer reports **715 changed groups**, each listed with its reason in `identity/changed-bodies.md`; full instruction diffs remain in `build/persistfix2/identity/changed-bodies.json.gz`. The supplemental `identity/reason-details.json` labels 335 linked differences as memory-reference annotations only, 315 as changed instruction records/group shape, and 65 as added/removed linked groups. The annotation classification does not establish referenced-data identity. The object tool’s ordinary-command assertion flags the intentional changed handlers; this diagnostic did not stop the work.

All **74 GET/SET/MGET/MSET entry/execution bodies** retain the same instructions, constants and resolved targets. The stock object comparison directly matches 73; the remaining DB0 xshard body has three same-section LEA displacements to the same unchanged destructor, without ELF relocations. Those references were resolved explicitly. One linked nearest-symbol literal label differs, but its eight loaded bytes are identical. No comparison algorithm was weakened. See `hot-resolved-identity.json` and `identity-object-inventory.json`.

All old field offsets and sizes match in both database runtimes: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624; AofManager 976, SnapshotManager 792 and Server 141696 are also unchanged. The errno and signal policies use existing alignment bytes. Shard ownership, QSBR, immutable replacement, RYOW, ROB and native TOMOAOF format remain intact.

Known scope limits: native AOF writer failure remains terminal until restart; automatic storage-recovery retry is not added. A separately observed existing SAVE telemetry difference remains: failed synchronous SAVE sets TomoKV's `rdb_last_bgsave_status=err` and does not count a save attempt, while Redis retains background-save status and counts the attempt. This is outside the three PS4.13 register cases and preserves the existing psfix policy; the additional SAVE-error probe records INFO and asserts the exact reply. Rewrites themselves do not change the RDB baseline, save count or last-save status.

Completed test data is retained in `build/persistfix2/completed-large-test-data.tar.gz`: 196 datasets, 12,098,404,166 uncompressed bytes stored in 225,704,164 bytes. Every archived file's SHA-256 was verified before its uncompressed copy was removed. `archived-test-data.json` records all file hashes and the archive hash. Requested binaries, production objects and required unit build targets remain available.

### Arms and maintainer merit request

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/tomokv-persistfix2-pre` | `85bf1643126b63a140cf864ffa63c8d7abe75ebdb161831c3c3a9a7d84e6b0aa` |
| POST | `build/tomokv` | `edbdf2c72fae34a716669b5b522954df8b288d6a4fd0611520e41ce6cc992d43` |
| PAD-A | `build/tomokv-persistfix2-pad-a` | `2a444235324881c04d1740615c9c5ae02e4c6bf6217ffc4adf858140eb850550` |
| D8 planted control | `build/tomokv-persistfix2-control-d8` | `45146dfab18e1a64b8907457d6e6a387f05e5fdcf4bbb01405cf3c8f9919d56a` |

PAD-A is **(A) behaviour twin**: unmodified PRE implementation objects with unreachable padding, relocated to the final POST total .text size and start address. PRE .text is 8,217,911 bytes; POST and PAD-A are 8,226,151. Individual function placement and data sections are not a symbol-for-symbol candidate layout match, so this control does not isolate every local alignment effect. The planted D8 control is separate and excluded from merit measurement.

**NOT RUN, reserved for the maintainer:** performance benchmarks, measurement load generators and full `tests/gate.sh iteration`. No throughput claim is made. Use the gate's ABBA instrument with `GATE_ABBA_CELLS=docs/lbplanner/generic-cells.txt`, balanced PRE/POST and PRE/PAD-A comparisons on a quiet box. Server core pool 64–71, clients 72–79, no SMT, ports within 36800–36899; preserve every cell's own worker count, offered load, pipeline, read-local, atomic and connection settings, including the four-worker latency cells. Matched-load rate/latency decides merit; cycles/op, IPC and instructions/op explain it. Do not average away a regressed cell.

| Cell | PRE | POST | PAD-A | Verdict |
|---|---|---|---|---|
| h05 | pending | pending | pending | maintainer measurement |
| h06 | pending | pending | pending | maintainer measurement |
| p8g | pending | pending | pending | maintainer measurement |
| p8s | pending | pending | pending | maintainer measurement |
| d1g_l0 | pending | pending | pending | maintainer measurement |
| d1s_l0 | pending | pending | pending | maintainer measurement |
| m8g_l0 | pending | pending | pending | maintainer measurement |
| v1g_l0 | pending | pending | pending | maintainer measurement |
| d128g_l0 | pending | pending | pending | maintainer measurement |
| d32g_l1 | pending | pending | pending | maintainer measurement |
| d8s_l1 | pending | pending | pending | maintainer measurement |
| d32s_l1 | pending | pending | pending | maintainer measurement |
| x9_32_l1 | pending | pending | pending | maintainer measurement |
| x9_32_l0 | pending | pending | pending | maintainer measurement |
