persistfix3b — merge both AOF recovery harness hardenings

Worktree/branch: `/home/user/Projects/cx-persistfix3`, `cx-persistfix3`.
Ran `git fetch origin cpp && git merge origin/cpp` against `aee02e847`.
Merge resolution: `0abf75313`, parents `a817f27ab` and `aee02e847`.
This report is committed separately. No push.

Resolved both conflicts in `tests/persistfix.py` and `tests/gates_test.py`.
There is now one `Run.ready()` implementation. It preserves:

- Mainline's INFO Server `process_id == child.pid` check for readiness and
  every additional client, with fatal `persistence peer PID mismatch` errors.
  Mismatch diagnostics also include the observed process's cmdline.
- Mainline's `processes.jsonl` evidence: `spawn`, INFO peer observations for
  `ready`/`client`, `unanswered_peer`, and `reap`, with PID, boot, port and
  timestamps. Spawn argv/log and reap status remain recorded.
- The lane's `/proc/net/tcp{,6}` ownership checks, before spawning at either
  boot and around readiness. Additional clients also check ownership before
  connecting. Foreign owners fail with PID/cmdline without being retried.
- The fresh child log's exact listening banner and INFO/PING on one connection.
  Warmup and recovered GETs retain that verified connection. `server-N.json`
  retains PID, the explicitly labeled harness boot UUID, INFO fields, readiness
  evidence, and exit/failure details; any server-supplied run_id stays separate.
- Recovery failure messages beginning `recovered server exited N: <log tail>`
  when the child exited, using the final 8192 log bytes. Empty logs and children
  still running are reported explicitly. The bounded natural-exit wait and
  original failure reason are preserved.

Both regression methods remain:
`test_driver_identity_and_recovery_diagnostics` and
`test_recovery_requires_owned_pid_reply_and_records_the_peer`.
The latter now supplies the required banner and PONG, verifies no connection
is attempted for an empty log, and checks that successful readiness retains
the peer. Its reset, wrong/missing PID, closed rejected peers, and JSONL checks
remain active. The existing two-boot self-test also verifies spawn/ready/reap
events, argv/log, statuses, and their correspondence to `server-N.json`.

Executed serverless validation, all pinned to cores 112–127:

```sh
taskset -c 112-127 python3 -B tests/persistfix.py --self-test
taskset -c 112-127 python3 -B tests/gates_test.py SchedulerWiring PersistfixWiring
```

- Identity self-test: **14/14 PASS**.
  Log: `build/persistfix3b/identity-selftest.log`.
- SchedulerWiring + PersistfixWiring: **20/20 PASS**, 74.891 seconds,
  including both recovery methods and the 14 nested identity tests.
  Log: `build/persistfix3b/wiring-selftest.log`.
  The scheduler failures recorded in the original persistfix3 report did not
  recur on this merged tree. No scheduler assertions or deadlines were edited.
- AST comparison: all **14 existing live exercise assertions unchanged**;
  no duplicate Run methods; both regression methods present.
- `src/`, `tests/gate.sh`, `tests/fixtures/nullrefresh-ledger-labels.json`,
  `tests/persistfix_checks.py`, `tests/persistfix_unit.cc`, and
  `tools/persistfix_controls.py` are byte-identical to `aee02e847`.
  Receipt: `build/persistfix3b/preservation.json`.
- `git diff --check` and staged diff check: PASS.

No server, benchmark, load generator, build, live recovery case, or gate was
run in this addendum. The maintainer's reported 10/10 kill/1s/uring passes
against `aee02e847` are prior live evidence, not executions by this lane.

The eight gate labels remain
`AOF in-window {kill,term} recovery ({1s,2s}, {epoll,uring})`.
Quick/full row delta: **0 / 0**; mainline's 506-row gate is unchanged.
Neither EXPECT_* nor the label fixture was edited relative to mainline.

No performance arms or PAD are requested. For the maintainer's landing gate,
retain all eight positive recovery cells and the original four live PRE
negative controls: old-ack/2s/kill and old-close/2s/term, each on epoll and
uring, at 8 cores / 16 shards / 6 io + 2 ex. Acceptance remains eight positive
passes and four expected defect-specific failures: lost marker for old-ack,
and `persistence shutdown must drain` for old-close. Startup/identity failures
do not qualify as PRE witnesses. All existing serverless PRE controls are
unchanged. Review both artifact formats together for recovered PID evidence.
