# abbaflake — gate self-test PID publication

Worktree: `/home/user/Projects/cx-sortstore`; branch: `cx-sortstore`.
PRE: `9d9fad801` (the completed SORT lane). Fix: `e689e2e83`.
Only `tests/abbagate.py` changes in the fix commit. Existing SORT commits and
`EXPECT_QUICK` / `EXPECT_FULL` are untouched. No new gate row: expected counts
remain unchanged. The ABBA command gains three unittest cases (95 -> 98).
No server, load generator, gate invocation, benchmark, or push was run.

## Sites fixed (POST line numbers)

| Site | Change |
| --- | --- |
| `tests/abbagate.py:4164`, `tests/abbagate.py:4166`, `tests/abbagate.py:4167` | The compiler fixture writes a sibling temporary file, closes it, then publishes `compiler.pid` with `os.replace`. |
| `tests/abbagate.py:2141`, `tests/abbagate.py:4169` | The shared self-test reader retries missing files, empty text, and values rejected by `int`; it returns the parsed integer directly and keeps the caller's original five-second deadline. |
| `tests/abbagate.py:2153`, `tests/abbagate.py:4179` | Every `/proc/<compiler>/stat` read handles `FileNotFoundError` and `ProcessLookupError`. Zombie/dead/reaped means stopped; a live state at the original deadline still fails. Removed the exists/read gap and the extra final read. |
| `tests/abbagate.py:4187` | Real-child negative control holds the PID file empty, then publishes atomically after 75 ms. A pipe handshake forces both the old reader and the fixed reader to sample that same empty file; a missed window fails. |
| `tests/abbagate.py:4236` | Missing, empty, and malformed PID input must retry or fail at the deadline; valid integer text succeeds. |
| `tests/abbagate.py:4250` | A process disappearing on a later read is accepted as reaped for both kernel errors; a persistently live child fails at the deadline. |

The reader's short sleeps are bounded polling backoff, never evidence of readiness.
The only deliberate fixed delay is the 75 ms fault window in the negative control.

## Negative control

`taskset -c 112-127 python3 build/abbaflake/targeted.py`: **4/4 passed**.
The control explicitly asserts the old `int(pidfile.read_text())` raises `ValueError`
on the empty file, then calls the actual fixed reader and checks the child's PID.

`taskset -c 112-127 python3 build/abbaflake/targeted.py read-once`: **failed as
required**, exit 1, one error: `ValueError: invalid literal for int() with base 10: ''`.
This uncommitted in-memory mutation replaces only the fixed reader with the old
one-shot read. Thus deleting the retry really makes the new control red; it does
not merely test a separate copy of a supposedly correct reader.

Logs: `build/abbaflake/targeted.log`, `build/abbaflake/read-once-control.log`.

## Gate command and repeated verification

`tests/gate.sh:2320` defines `job_abba_selftest`; `tests/gate.sh:2335` invokes
`py tests/abbagate.py --self-test`. The `py` wrapper at `tests/gate.sh:622` calls
`python3 "$@"` after the gate's quiet check. The exact serverless command repeated is:

```sh
taskset -c 112-127 python3 tests/abbagate.py --self-test
```

PRE runs from the unchanged local snapshot `build/abbaflake/pre`; POST runs from
this worktree. Each phase runs the command in a serial 20-iteration loop, with
an eight-job compile loop in parallel:

```sh
taskset -c 112-127 python3 build/abbaflake/repeat.py pre-results build/abbaflake/pre
taskset -c 112-127 python3 build/abbaflake/repeat.py post-results .
```

The driver inherits and asserts affinity 112-127, and each compile loop repeatedly
runs `make -r -s -B -j8` on eight compile-only copies of `src/cmd/glob.cc` in
`build/abbaflake/load`. It never links or executes a server. PRE and POST loops
overlap, so their eight-job compile loads overlap too; these are correctness
stress counts, not performance comparisons. Active compiler affinity was also
checked through `/proc` (`build/abbaflake/compile-affinity.json`). Other lanes were also compiling
on CPUs 112-127 during these runs; `build/abbaflake/shared-compile-load.json`
records that observed contention. No other lane's process was changed or stopped.

| Version | Completed | Pass | Fail |
| --- | ---: | ---: | ---: |
| PRE `9d9fad801` | 20 | 20 | 0 |
| POST `e689e2e83` | 20 | 20 | 0 |

The original race **did not reproduce naturally in the 20 PRE repetitions**.
The deliberately widened window is the new real-child control above: the final
PID file is held empty until both readers observe it, then publication is delayed
75 ms. The old one-shot read raises the exact reported `ValueError`; the fixed
reader waits successfully. This is controlled reproduction, not a claimed
spontaneous failure in the PRE loop.

Each PRE command ran all 95 ABBA, 10 saturation, and 7 calibration tests.
Each POST command ran all 98 ABBA plus the same 10 saturation and 7 calibration tests.

Per-run outputs and return codes: `build/abbaflake/pre-results/`,
`build/abbaflake/post-results/`; each contains `results.json`, 20 `run-NN.log`
files, `compile.log`, and a completed-compile-round journal. PRE completed 4,750
compile batches; POST completed 4829 batches. The final batch is intentionally
terminated when its phase finishes; those final TERM messages are expected. Preliminary runs
whose compile harness failed during setup were rejected before these loops and
are not counted (`build/abbaflake/pre-load-setup-rejected/`).

The other seven commands in the same row are also checked, in the row's order:

```sh
taskset -c 112-127 bash -c 'python3 tests/gate_quiet.py --self-test &&
python3 tests/gate_measurements.py --self-test &&
python3 tests/background_environment_test.py &&
python3 tests/gate_history.py self-test &&
python3 tests/gate_process_test.py &&
python3 tests/gates_test.py &&
python3 tests/tailgen_stall.py --self-test'
```

Companion run under both compile loads: quiet **8/8**, measurements **11/11**,
background **11/11**, history **55/55**, process cleanup **12/12** passed.
`gates_test.py` ran 56 tests and reported **four failing subcases**, all scheduler
fixture exit 124 at its existing 45-second timeout, not a PID parse error:
`test_empty_fragment_and_explicit_failure_cannot_turn_green` (empty and red),
`test_nonzero_worker_return_cannot_be_hidden_by_a_pass_fragment`, and
`test_worker_exit_before_done_is_a_failure`. The chain consequently did not reach
tailgen; running `taskset -c 112-127 python3 tests/tailgen_stall.py --self-test`
separately passed **3/3**. No deadline or assertion was weakened.

Logs: `build/abbaflake/companion-selftests.log`, `build/abbaflake/tailgen-selftest.log`.
The four scheduler artifact directories are named in the companion log.
Running those same three unittest methods (four subcases) on untouched PRE
`9d9fad801`, still pinned to 112-127 under the compile loads, reproduced all four
exit-124 scheduler timeouts. Log: `build/abbaflake/companion-pre-controls.log`.
After both stress loops stopped, the final command
`taskset -c 112-127 python3 tests/gates_test.py` passed **56/56** in 236.632 s.
Log: `build/abbaflake/companion-final-gates.log`. The earlier four failures remain
recorded above; the final pass does not replace or hide them. All other companion
commands had already passed. At the recheck, `/proc` showed no remaining owned
compiler process and no other compiler on 112-127 (`build/abbaflake/load-cleanup.json`).

## Audit: unchanged sites and why they are sound for this race

The transitive local import closure, including imports inside functions and
self-tests, contains 18 modules. `build/abbaflake/audit-files.txt` lists them;
`build/abbaflake/audit-io.txt` indexes 433 candidate file/process call sites. The audit
also followed the shell publishers/consumers in `gate.sh` and the other commands
in the ABBA row. The table lists each existence/poll handoff or related producer
that needed a completion/ownership check; plain synchronous fixture writes and
reads have no concurrent publisher.

| Inspected sites | Reason unchanged |
| --- | --- |
| `tests/abbagate.py:376`; `tests/gateplan.py:69`, `tests/gateplan.py:74`; `tests/abba_worker_affinity.py:26` | CPU topology comes from kernel sysfs, not a user-space file being created and filled. Missing/unreadable topology cannot certify a placement. |
| `tests/abbagate.py:914`, `tests/abbagate.py:917`, `tests/abbagate.py:926` | Reference manifest/executable discovery reads configured inputs, not a completion mailbox. Identity and ambiguity checks remain strict. |
| `tests/abbagate.py:989`, `tests/abbagate.py:1040`, `tests/abbagate.py:1044`, `tests/abbagate.py:1869`; `tests/gate_measurements.py:167`; `tests/gateplan.py:155`; `tests/load_calibration.py:160`; `tests/legacy_reorder_witness.py:364` | Binary discovery checks availability/identity. Reference compilation is explicitly waited for before the binary is consumed; no exists-as-completion protocol. |
| `tests/abbagate.py:939`, `tests/abbagate.py:946`, `tests/abbagate.py:949`, `tests/abbagate.py:952` | `Children.start` opens the log before spawning. `stop` uses its owned Popen and waits after terminate/kill; it reads no published PID file. |
| `tests/abbagate.py:962`, `tests/abbagate.py:972`, `tests/abbagate.py:983` | `stop_build` discovers only the owned session, catches disappearance at the actual `/proc` read, signals only those PIDs, and waits for its Popen. Kernel proc records are not Path.write_text publications. |
| `tests/abbagate.py:1169`, `tests/abbagate.py:1180`, `tests/abbagate.py:1184`, `tests/abbagate.py:1195`; `tests/abba_profile.py:181`, `tests/abba_profile.py:184`, `tests/abba_profile.py:196`, `tests/abba_profile.py:210`, `tests/abba_profile.py:215`, `tests/abba_profile.py:216`; `tests/abba_worker_affinity.py:38`, `tests/abba_worker_affinity.py:40`, `tests/abba_worker_affinity.py:55`, `tests/abba_worker_affinity.py:62` | Measurement CPU endpoints require live, matching identities and complete kernel records. Exiting/disappearing mid-measurement is invalid evidence and must fail, unlike waiting for an intentionally killed child to stop. |
| `tests/abbagate.py:1417`, `tests/abbagate.py:1427`, `tests/abbagate.py:1428`, `tests/abbagate.py:1498`, `tests/abbagate.py:1564` | Liveness guards fail a measurement if a child exits. The log was created before spawn; its suffix is diagnostic text, never a completion record. Boot readiness comes from the connection and matching INFO PID. |
| `tests/abbagate.py:1239`, `tests/abbagate.py:1589`, `tests/abbagate.py:1600`, `tests/abbagate.py:1620`; `tests/abba_worker_affinity.py:242` | All generators are waited for before parsing their JSON/HDR results. A partial/malformed completed result still fails. |
| `tests/abbagate.py:1808`; `tests/load_calibration.py:138` | Quiet markers carry only mtime/existence, no payload. Missing/recent markers reject work; a disappearing stat also fails closed. |
| `tests/abbagate.py:843`, `tests/abbagate.py:852`, `tests/abbagate.py:869`, `tests/abbagate.py:1309`, `tests/abbagate.py:1657`, `tests/abbagate.py:1860`, `tests/abbagate.py:2041`, `tests/abbagate.py:2087`, `tests/abbagate.py:2125`; `tests/load_calibration.py:133`; `tests/legacy_reorder_witness.py:329`, `tests/legacy_reorder_witness.py:342`, `tests/legacy_reorder_witness.py:406`; `tests/abba_simple.py:50` | Reports are read after the synchronous producer returns or the gate waits for its child. Configured standing-null inputs are validated as complete evidence, not awaited mailboxes. Progress-file existence is never accepted as final success. |
| `tests/abbagate.py:3443`, `tests/abbagate.py:4149`, `tests/abbagate.py:4150`, `tests/abbagate.py:4171`, `tests/abbagate.py:4172`, `tests/abbagate.py:4181` | Self-test absence/liveness assertions and finalizers do not use existence to infer file content. |
| `tests/_gate_process.py:100`, `tests/_gate_process.py:103`, `tests/_gate_process.py:107`, `tests/_gate_process.py:127`, `tests/_gate_process.py:171`, `tests/_gate_process.py:173`, `tests/_gate_process.py:177`, `tests/_gate_process.py:178`, `tests/_gate_process.py:193`, `tests/_gate_process.py:197`, `tests/_gate_process.py:199`, `tests/_gate_process.py:203` | Owned Popen/INFO establish identity; the PID file is a diagnostic artifact, not readiness. The log is pre-created; final shutdown JSON is read only after stop_process waits. Quiescence/exit records are synchronous writes consumed after the context returns. |
| `tests/abba_instrument.py:44`, `tests/abba_instrument.py:51`, `tests/abba_instrument.py:71`, `tests/abba_instrument.py:77`; `tests/gate_receipt.py:64` | Source/module discovery uses metadata-and-content fingerprints with before/after identity checks. Source changes are invalidation, not partial readiness to retry. |
| `tests/gate_measurements.py:41`, `tests/gate_measurements.py:389`, `tests/gate_measurements.py:391`; `tests/gate_receipt.py:191` | The calibration ledger is fully written and validated at its temporary name, then atomically replaced; inventory reads immutable configured data. |
| `tests/gate_quiet.py:55`, `tests/gate_quiet.py:57` | Optional `/proc/net/tcp6` availability is a kernel feature check. Port data is a kernel snapshot, not an application-produced completion file. |
| `tests/gate_history.py:177`, `tests/gate_history.py:179`, `tests/gate_history.py:264`, `tests/gate_history.py:303`, `tests/gate_history.py:312` | History readers hold the shared flock; appenders hold the exclusive flock through complete record publication. Empty history before the first append is valid. The stat-bound index/checkpoint is validated and atomically published; incomplete JSONL is rejected. |
| `tests/gate_history.py:509`, `tests/gate_history.py:519`, `tests/gate_history.py:649`, `tests/gate_history.py:659`, `tests/gate_history.py:698`, `tests/gate_history.py:700`, `tests/gate_history.py:715`; `tests/gate.sh:319`, `tests/gate.sh:340`, `tests/gate.sh:342` | Timeout markers, cancellation requests, and cancellation receipts publish via same-directory rename. Consumers validate the whole exact record and PID/start/generation. No partial record is accepted. |
| `tests/gate_history.py:524`, `tests/gate_history.py:581`, `tests/gate_history.py:1008`, `tests/gate_history.py:1085`, `tests/gate_history.py:1139`, `tests/gate_history.py:1143`, `tests/gate_history.py:1161`, `tests/gate_history.py:1169` | Proc identity readers catch disappearance where they read; bounded cleanup keeps explicit PID/start ownership and waits/reaps its own children. |
| `tests/gate_history.py:1066`, `tests/gate_history.py:1071`, `tests/gate_history.py:1081`, `tests/gate_history.py:1082`, `tests/gate_history.py:1255`, `tests/gate_history.py:1258`, `tests/gate_history.py:1354`, `tests/gate_history.py:1355`, `tests/gate_history.py:1446`, `tests/gate_history.py:1451`, `tests/gate_history.py:1476`, `tests/gate_history.py:1721` | Read/assert only after the synchronous fixture/watch call or subprocess completion; no poll of a payload file's creation. |
| `tests/gate_history.py:1237`, `tests/gate_history.py:1238`, `tests/gate_history.py:1246`, `tests/gate_history.py:1307`, `tests/gate_history.py:1313` | The ready/TERM markers are intentionally empty flags. Their existence is their entire value; no following content read. |
| `tests/gate_history.py:1433`, `tests/gate_history.py:1435`, `tests/gate_history.py:1503` | The shell already waits for nonempty PID bytes (`-s`), not existence; the integer is read only after the owning fixture subprocess finishes and its child has been reaped. |
| `tests/gate_receipt.py:139`, `tests/gate_receipt.py:150`, `tests/gate_receipt.py:154`, `tests/gate_receipt.py:165`, `tests/gate_receipt.py:310`, `tests/gate_receipt.py:337`, `tests/gate_receipt.py:429`, `tests/gate_receipt.py:435`, `tests/gate_receipt.py:458`, `tests/gate_receipt.py:467`, `tests/gate_receipt.py:521`; `tests/gate.sh:1165` | Begin/bind/coordinator/finish are synchronous stages; binding completes before the worker's done marker. Exclusive JSON creation is not itself used as completion. Receipt discovery strictly validates full JSON and rejects unfinished evidence; it does not wait for a concurrent gate to finish. Shared null/baseline replacement is atomic. |
| `tests/gate_receipt.py:167`, `tests/gate_receipt.py:448`, `tests/gate_receipt.py:450`, `tests/gate_receipt.py:564`, `tests/gate_receipt.py:565` | Temporary cleanup checks are not reads; baseline publication is atomic. Hook installation checks immutable configuration/prior synchronous state. |
| `tests/gate_receipt.py:763`, `tests/gate_receipt.py:764`, `tests/gate_receipt.py:805`, `tests/gate_receipt.py:811`, `tests/gate_receipt.py:896`, `tests/gate_receipt.py:924`; `tests/abba_profile.py:515`, `tests/abba_profile.py:523`; `tests/abba_worker_affinity.py:335` | Self-test reads/assertions follow completed synchronous calls or completed subprocesses; child cleanup uses Popen, not a polled PID file. |
| `tests/gates_test.py:415`, `tests/gates_test.py:417`, `tests/gates_test.py:584`, `tests/gates_test.py:586`, `tests/gates_test.py:623`, `tests/gates_test.py:630`, `tests/gates_test.py:659`, `tests/gates_test.py:661`, `tests/gates_test.py:669`, `tests/gates_test.py:690`, `tests/gates_test.py:1136`, `tests/gates_test.py:1151`, `tests/gates_test.py:1542` | Companion audit: result reads follow subprocess completion; ready/cleaned flags carry no parsed payload. The ready.json reader already retries missing files and JSONDecodeError to its existing deadline, and dispatch.json is closed before ready.json is written. |

`_lib.py`, `_abba_test_fixtures.py`, `abba_evidence.py`, and `abba_workloads.py`
have no file-publication readiness handoff. `abba_saturation.py` consumes explicit
snapshot files, with no existence poll. Other synchronous JSON/fixture I/O in the
index has no concurrent writer or completion-by-existence check.

## Requested baseline diff

`git diff b8fe404e2 --stat` (includes the completed SORT lane and the existing
reference rebaseline; those changes are not part of abbaflake):

```text
 MEASURE-REQUEST-abbaflake.md | 186 +++++++++++++++++++++++++++++++++++++++++++
 MEASURE-REQUEST-sortstore.md | 126 +++++++++++++++++++++++++++++
 Makefile                     |   2 +-
 src/cmd/cmdmeta.cc           |  10 ++-
 tests/abbagate.py            | 125 ++++++++++++++++++++++++-----
 tests/differ.py              |   9 +++
 tests/gate_measurements.json |   8 +-
 tests/multidb.py             |   2 +
 tests/multidb_unit.cc        |   6 ++
 tests/sortstore.py           | 129 ++++++++++++++++++++++++++++++
 tests/sortstore_cases.tsv    |  67 ++++++++++++++++
 tests/sortstore_checks.inc   | 142 +++++++++++++++++++++++++++++++++
 tests/sortstore_controls.py  |  93 ++++++++++++++++++++++
 13 files changed, 879 insertions(+), 26 deletions(-)
```
