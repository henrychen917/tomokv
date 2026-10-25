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

Current lane: `/home/user/Projects/cx-persistfix2`, branch `cx-persistfix2`, PRE `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`. The earlier report above is historical. No push. Builds use CPUs 64–79, `-j16`; gate jobs use servers 64–71, clients 72–79, 16 shards, ratio 6:2, ports 36800–36899.

PS4.6 reproduced on PRE in all four 1s/2s × epoll/uring legs through the real `GATE_ONLY_JOBS=persistfix2_lastsave` interface. Redis 7.4 passed every oracle leg. POST passes the same eight legs: LASTSAVE and RDB telemetry remain unchanged during/after a rewrite, and `aof_rewrites` counts an attempt at start, as Redis does. Evidence: `docs/persistfix2/{pre,post}-lastsave/`. The RDB change baseline, last-save status and save count already excluded rewrites; native snapshot-cut and AOF byte/record counters describe their own mechanisms. The LASTSAVE correction also preserves the save cron elapsed-time origin.

Interim row delta: DQ=+1 / DF=+1, collected at `collect_job persistfix2_lastsave`, before the quick-tier exit. EXPECT constants remain unchanged. Remaining items and final proof are being completed.

PS4.12: reproduced FORCE refusal, ABORT combination parsing, repeated-modifier arity, absent signal policies and non-oracle error text on PRE. POST passes the complete directed oracle/target matrix (1s/2s × epoll/uring), including failing/successful saves, all legal flag sets, illegal combinations, CONFIG and boot signal policies, and shutdown during an observed BGSAVE. NOW bypasses replication waiting; this single-node server has none, and NOW alone still refuses a failed save. FORCE logs the failed save and exits 0 without a reply. A pending signal request can be aborted before save admission. Existing Config padding holds the two policy bytes; no listed layout changes. Evidence: `docs/persistfix2/{pre,post}-shutdown/`. The shutdown unit passes; its timeout assertion now uses the exact oracle refusal while retaining the required stalled-owner witness. Its active-save schedule now requires cancellation and a fresh final epoch. An initial extra EXEC probe incorrectly expected queueing; both oracle and target rejected it. The corrected probe asserts the exact rejection and EXECABORT.

The combined shutdown/production-unit gate build was interrupted before row execution so subsequent header changes do not force redundant complete instrumented builds. It is not a pass; the complete job will be rerun after the final source changes. Interim cumulative DQ=+2 / DF=+2.

PS4.13: the directed row reproduces all three register cases on PRE in both modes and engines: disabled-AOF refusal, rewrite scheduling reply, and BGSAVE option parsing. POST uses the existing native snapshot coordinator for an explicit rewrite while AOF is off; it creates a native base plus empty increment and durable manifest without arming producers or ordinary AOF recording. Recovery restores that explicit cut; later AOF-disabled writes are absent. Repeated scheduled rewrite requests coalesce. BGSAVE SCHEDULE waits for an active rewrite; ordinary BGSAVE reports Redis's exact error. SAVE may finish the shared rewrite capture before taking its own cut. Invalid BGSAVE options return syntax errors, and synchronous SAVE failure returns the oracle's exact `ERR`.

The extended battery exposed and fixed a transition race between clearing the AOF-active flag and the snapshot coordinator reaching Idle. An initial directory-error cleanup bug and an incorrect new SAVE-error status assertion were corrected before the complete matrix was rerun. Existing, separately observed telemetry difference outside the three PS4.13 register cases: a failed synchronous SAVE sets TomoKV's `rdb_last_bgsave_status=err` and does not count an RDB save attempt; Redis retains its previous background-save status and increments its save-attempt count. This lane preserves the existing tests/psfix.py policy; the directed evidence records both INFO results and asserts only the exact error reply for this additional probe. No claim that all INFO fields are Redis-identical is made.

PS4.13 complete gate evidence: `docs/persistfix2/{pre,post}-commands/`; every oracle leg passes, every PRE target leg fails, every POST target leg passes. Cumulative DQ=+3 / DF=+3.


PS4.15 coverage audit: all previously fixed listed findings already have gate coverage. The missing D8 policy is now covered and fixed. A real file-size limit is lowered to the current increment boundary after an acknowledged write reaches the file, so the next write receives deterministic EFBIG without a short-write/ENOSPC ambiguity. Both fsync policies (`no`, `everysec`), modes, engines, normal/reorder dispatch, and armed fused reads are exercised. The row requires observed `aof_last_write_status=err`, exact oracle MISCONF replies, continued reads, no rejected mutations, abort of prequeued writes with WATCH cleanup, and completion of a read-only transaction. PRE fails; all POST/oracle legs pass. A separate binary with only the post-error admission refusal removed fails every target leg, while all its oracle legs pass. Control source/binary exist only under build/; it is never a shipping arm. See `docs/persistfix2/{pre,post,control}-errors/` and `control-d8.json`.

The errno occupies existing AofManager alignment bytes. The ordinary and reorder dispatch paths share the same cold refusal; the failed-state flag is the added per-operation test. Existing `always` policy exit behavior is retained. Native writer failure remains terminal until restart; automatic retry after storage recovery is not added by this test-gap fix.

| Finding | Existing source coverage before this lane | New coverage required |
|---|---|---|
| PS4.1 | job_aof: aoffix2 snapshot, both modes/engines | none |
| PS4.2 | job_aof: aoffix2 filename, both modes/engines | none |
| PS4.3 | job_aof: aoffix2 large and large_placed, fused/both engines | none |
| PS4.4 | job_aof: aoffix2 error, always policy, both modes/engines | D8 no/everysec refusal row |
| PS4.5 | job_aof: tickets, exec_tickets, resurrection, both modes/engines | none |
| PS4.7 | job_aof: off-writer acknowledgement, everysec/always, both modes/engines | none |
| PS4.8 | job_aof: rewrite_fail2, both modes/engines | none |
| PS4.9 | job_aof: manifest_missing, both modes/engines | none |
| PS4.10 | job_snapshot: savefix acknowledged-write recovery, command/SIGTERM, both modes/engines | none |

Final additions: **DQ=+4, DF=+4**, all four collect_job lines precede the quick-tier exit. Maintainer-owned counts should become **EXPECT_QUICK=772** (768+4), **EXPECT_FULL=789** (785+4). Neither constant was edited. The explicit label fixture contains the four reviewed additions and matches all 789 source declarations, with no missing/extra labels. Its raw checker correctly refuses the still-785 constant; the prospective in-memory 789 check passes. Evidence: `label-inventory.json`, `label-fixture-check.log`.


Identity and layout: the unmodified object and strict linked identity tools were run against PRE. They report 477 changed object bodies, 92 inventory additions/removals and 715 strict linked groups; these are diagnostic differences, not a stopping rule. Every changed linked group and its reason is listed in `docs/persistfix2/identity/changed-bodies.md`; full instruction diffs remain in `build/persistfix2/identity/changed-bodies.json.gz`. The raw object tool rejects intentional changed command handlers. Of 74 actual GET/SET/MGET/MSET entry/execution bodies, 73 match its relocation normalization directly. The remaining DB0 xshard_execute has three same-section LEA displacements to the same unchanged ScriptWorkbench destructor; the compiler emitted no ELF relocations for them. Resolving those exact references makes the instruction stream identical. Its one strict linked literal-label difference loads the same eight bytes (`ffffffff00000000`); only objdump's nearest-symbol label changed. No equality tool was weakened. `hot-resolved-identity.json` records these additional explicit checks.

All existing sizes and field offsets match PRE, including both database runtimes: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624; AofManager 976, SnapshotManager 792 and Server 141696 also remain unchanged. No shard ownership, QSBR, immutable replacement, RYOW, ROB or native TOMOAOF format change is introduced.

Merit request — maintainer only, **not run by this lane**. Use the gate's ABBA instrument and the exact 14-cell file `docs/lbplanner/generic-cells.txt`, with balanced PRE/POST and PRE/PAD-A comparisons on a quiet box. Use eight server cores in one CCX (64–71) and load cores 72–79, no SMT, ports within 36800–36899; preserve every cell's offered load, pipeline, read-local, atomic and connection settings. `GATE_ABBA_CELLS=docs/lbplanner/generic-cells.txt` selects that source. Record per-cell matched-load rate, cycles/op, IPC and instructions/op, plus the designated latency metric for d1g_l0/d1s_l0. Rate/latency at matched offered load decides merit; instruction count alone does not. Do not average away a regressed cell.

PAD-A is **(A) behaviour twin**: unmodified PRE implementation objects, padded and relocated to POST's total .text size and start address. Its individual function positions and data sections retain PRE behavior/layout, so it does not isolate every local alignment effect. The added padding is unreachable. The D8 planted control is a separate correctness artifact and is excluded from the merit request. POST .text is 8,226,151 bytes versus PRE's 8,217,911; PAD-A is 8,226,151. No throughput claim is made.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/tomokv-persistfix2-pre` | `85bf1643126b63a140cf864ffa63c8d7abe75ebdb161831c3c3a9a7d84e6b0aa` |
| POST | `build/tomokv` | `edbdf2c72fae34a716669b5b522954df8b288d6a4fd0611520e41ce6cc992d43` |
| PAD-A | `build/tomokv-persistfix2-pad-a` | `2a444235324881c04d1740615c9c5ae02e4c6bf6217ffc4adf858140eb850550` |

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

The four new collect_job lines are 5306–5309, before the quick-tier exit at line 5386 in this revision. Broader correctness receipts and final freshness results follow below when complete. Performance benchmarks, measurement load generators and the full iteration gate remain NOT RUN, as reserved for the maintainer.


PS4.12 qualification: the claim that NOW alone permits exit after a failed save is **NOT REPRODUCED**. PRE and Redis both refuse `SHUTDOWN NOW` when the final save fails, in all four 1s/2s × epoll/uring geometries (16 shards, six IO/two executor workers for split, cores 64–71, port 36800). FORCE is the modifier that permits that exit. NOW bypasses replica waiting, absent in this single-node architecture.

The complete PRE proof uses `build/persistfix2/pre-proof-source`: an isolated, disposable source snapshot below this worktree, with every production blob and Makefile verified identical to 05a5e01a9, plus the current gate fixtures. It reuses the frozen PRE objects. This allows the changed shutdown-unit fixture to link to PRE's implementation; the ordinary external-candidate gate interface alone would otherwise build that unit from POST sources. Its exact source-tree receipt is `pre-proof-source.json`.

Offline build freshness is complete on POST: `make -q all`, all 42 executable targets named by `job_production_units`, and `mdbqsbr-live-arms` return 0 (44 checks). Receipt: `docs/persistfix2/post-build-freshness.json`. PRE and POST hashes remain unchanged. An initial regression invocation pointed `REDIS74_ROOT` at the binary-only oracle directory; its preflight warning did not stop its workers. That invocation was terminated after detecting the overlap. Its results are excluded. The surviving run uses the complete Redis source tree, and every unit target's freshness was independently checked after the duplicate stopped.

Reply search evidence is `docs/persistfix2/reply-search.json`, including old/new rewrite and shutdown wording, BGSAVE errors, exact `ERR`, signal-policy diagnostics and AOF refusals. Registered consumers are covered by `aof-{epoll,uring}`, `snapshot-{epoll,uring}`, `climonfix`, `iofix-signal`, `router_uniform`, `aof_frame`, `aoforder`, both debug jobs, all four split/armed feature jobs, both fused jobs, dispatch arity/errors, atomic units/batteries and the standard differential matrix. CONFIG/INFO checks also include `serverfix_config`, `serverfix_scalar` and `serverfix_waitaof`. `psfix.py`, `shutsave.py` and `redisgap.py` are standalone historical drivers with no registered job; their occurrences do not identify additional gate rows. The serverless controls for the first two, differential driver, framing and DEBUG load are included in the proof queue. Historical rewrite child scripts choose ratio 4:4 on eight cores; their gate jobs retain that declared geometry. The new persistfix2 and ordinary split boots use ratio 6:2.

The first broad POST regression run found the historical rewrite-trigger row waiting for `aof_rewrites` alone to infer completion. Redis increments that field at start: the retained `post-lastsave/lastsave-oracle-*.log` records show `aof_rewrites=1` while `aof_rewrite_in_progress=1`, then the same attempt count after completion. The trigger fixture now additionally requires `aof_rewrite_in_progress=0` before its existing success/base/limiter assertions, for all three waits. No success assertion or arming witness is removed. Its printed count is named attempts. Both complete AOF jobs will be rerun on POST and PRE in both thread modes and engines; the initial failures remain evidence.

Initial dispatch arity/errors and uniform-router jobs could not bind the Redis oracle on port 36862: other lanes' outbound connections occupied even-numbered ports in this lane's range with TIME_WAIT sockets. These are environment failures, not reply comparisons. The three fixtures now use `port+2`, the third port already reserved by each gate slot, allowing odd target/oracle ports 36861/36863 without changing any assertion or row count. Their complete jobs are rerun on PRE and POST, with all four mode/engine legs retained. The standard differential runner uses target 36861 and oracle 36865, leaving 36863 for its required reader control.

POST regression receipts are archived under `docs/persistfix2/proof/` (each summary includes the original run path, per-job row counts and archive SHA-256):

| Run | Passing rows | Failed rows | Interpretation |
|---|---:|---:|---|
| post-initial | 384 | 5 | Two obsolete completion waits; three oracle bind failures, retained in full |
| post-aof-corrected | 109 | 0 | Release prerequisite plus all 54 AOF rows on each engine |
| post-extra | 15 | 0 | All port-corrected oracle legs, CONFIG/scalar/WAITAOF, auth and default-database jobs |

The corrected POST runs clear each of the five initial failures. PRE, fused persistence reruns, the standard differential matrix and serverless harness proof remain in the serial verification queue. All jobs use the gate's own job interface; no full iteration or performance tier is run.

PRE source proof checkout repair: the first production-helper attempt encountered two local checkout assumptions (generated sources must resolve beneath that checkout's real build directory; PAD unit builders need historical Git objects). That attempt was stopped after its compilation finished and is not counted as a completed regression run. The build directory now physically resides inside the PRE source checkout, with the original `build/persistfix2/pre` path retained as an alias. A read-only Git object alternate supplies the required existing history. No PRE production blob or binary changed. The restarted run built every helper successfully; **all 44 PRE freshness checks return 0**, including `make -q all`, the 42 executables and `mdbqsbr-live-arms`. Receipt: `docs/persistfix2/pre-build-freshness.json`.

The completed PRE regression run has **395 passing rows and five expected failures** (`proof/pre-regression`). Its four new persistfix2 rows fail in all 16 target legs; all 16 corresponding Redis legs pass. The changed shutdown-unit row fails precisely at `ABORT cancels a signal request before save admission`; its six live shutdown-persistence legs pass. Every other selected PRE job passes, including both complete AOF jobs, both snapshot jobs and the port-corrected dispatch/router jobs. This completes the 400-row PRE/POST comparison for that job inventory: POST clears all five behavior differences after the documented fixture corrections.

The complete POST fused persistence rerun passes **148/148 rows** (`proof/post-fused`): `GATE_TXN_FUSED=1` runs the historical AOF/snapshot boots in fused mode on both engines, and `GATE_SHUTDOWN_NET_IO=epoll` covers both shutdown thread modes on epoll. The earlier climonfix run covered both on io_uring. No leg is omitted from the jobs' nested matrices.

The matching PRE fused persistence rerun has **147 passing rows and one expected failure** (`proof/pre-fused`): the same pending-ABORT shutdown unit. Every live AOF, snapshot and shutdown leg passes. The required new/touched rows and related persistence jobs have now completed through the gate's own interface on both arms, in all declared modes and engines.

The first standard differential attempt was interrupted after its climon reader control exposed the target-plus-two reservation colliding with the oracle listener. This was a fixture-port failure before a tracking comparison, not DIFF-TRK-1. The complete matrix is restarted with target/control/oracle ports 36861/36863/36865, using the unmodified standard runner and unchanged seed inventory. The interrupted attempt is excluded.

D8 follow-up: a review found that FCALL admission must use the registered function flags. A directed reproduction on the first candidate failed in every mode/engine while every oracle leg passed: a declared no-writes function was refused after an AOF write error. The classifier now reads registry flags on the cold failed-state path, including writable functions invoked as FCALL_RO; owner execution rechecks the selected callback to cover library replacement. The expanded row also queues a read-only function before the error and requires its EXEC to complete. The corrected complete eight-leg job passes (`proof/functions-{reproduced,corrected}`). This follow-up changes the candidate binary; final arms, identity and regression receipts are being refreshed.

Final artifact refresh after the function-admission correction: the object audit covers all 110 objects in the production link recipe, listed in `identity-object-inventory.json`, and compares 18,338 function pairs. Unit instrumentation copies are excluded from that production inventory; the comparison algorithms remain unchanged. The raw ordinary-command assertion reports the intentional persistence/function changes. All 74 resolved GET/SET/MGET/MSET bodies and all old layout offsets remain equal. Final binary hashes are in the arm table above and `arms.json`. The final complete regression selection is running against this candidate.

D8 legacy-script follow-up: Redis admits legacy EVAL/EVALSHA and checks disk errors at nested write execution. The prior candidate refused even read-only legacy scripts, reproduced in all four target geometries while all oracle legs passed (`proof/eval-reproduced`). Nested refusal now follows Redis, including protected errors, repeated refused writes, reads before a write and scripts queued before the AOF error. The complete expanded job passes (`proof/eval-corrected`). An initial added Lua PFCOUNT probe encountered the existing native unsupported-command restriction; it was replaced with supported GET and repeated-refused-SET probes, each keeping exact oracle assertions. The 400-row run before this follow-up passed (`proof/before-eval-post-regression`); final artifacts and proof are refreshed again for this source correction.

After the legacy-script correction, the final linked audit reports 715 changed groups, all with reasons. The complete object audit compares 18,338 function pairs, with 477 changed bodies and 92 inventory changes. All old layouts and all 74 resolved hot command bodies remain equal. Final hashes are refreshed in the arm table and `arms.json`; the full selected regression inventory is rerunning against this candidate.

The final candidate `edbdf2c72fae34a716669b5b522954df8b288d6a4fd0611520e41ce6cc992d43` passes the complete selected 400-row POST inventory (`proof/final-post-regression`). The expanded D8 fixture fails on PRE and the rebuilt planted control in every target leg; every oracle leg passes, all four per-leg durability windows are observed, and the target failures show the otherwise refused mutation taking effect (`proof/final-{pre,control}-errors`). The final fused and differential proof continues.

Final fused persistence proof passes 148/148 rows (`proof/final-post-fused`). Both arms have 44/44 successful make-q checks. Every queued serverless check passes: gates_test, psfix_test, shutsave_test, differ_test, aof_frame_order_test, debug_load_test and flakeaudit_test. Their full logs and exact invocations are retained under `proof/final-serverless-*`. The final standard PRE/POST differential matrices are running on separate eight-core groups inside CPUs 64–79.

Final standard epoll/split differential proof passes 475/475 on both PRE and POST, with the full five-seed inventory, both atomic settings, all four MULTI repeats and mode equivalence. Evidence is under `proof/differ-final-{pre,post}-epoll-split`. The remaining engine/geometry pairs continue.

Final standard epoll/armed-fused differential proof passes 466/466 on both PRE and POST. The complete standard suite/seed inventory, four MULTI repeats and both armed-read witnesses are retained. DIFF-TRK-1 is not observed on either arm in these epoll runs; this does not establish that the existing intermittent issue is resolved. Evidence: `proof/differ-final-{pre,post}-epoll-armed-fused`. The io_uring matrices continue.

Final candidate and PRE io_uring/split standard-seed matrices each pass 475/475 (18m03s and 18m05s). Complete evidence is in `docs/persistfix2/proof/differ-final-{post,pre}-uring-split/`. Six of eight final differential matrices are complete; the io_uring armed-fused pair is running.
