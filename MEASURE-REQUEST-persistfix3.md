persistfix3 — AOF recovery harness identity and diagnostics

Worktree/branch: `/home/user/Projects/cx-persistfix3`, `cx-persistfix3`.
Launch: `aabc435ce`. First operation after checking the clean worktree was
`git fetch origin cpp && git merge --no-edit origin/cpp`, fast-forwarding to
`cd02ecbab`. Implementation: `fcffc88c5`; this report is committed separately.
No push. No server, benchmark, load generator, live recovery row, build, or gate
was run. All executed Python checks were pinned to cores 112–127.

The supplied failure is real: `server-2.log` has zero bytes, and the driver reached
GET after a connect-only readiness check. The old artifacts do not preserve the
recovered child's exit status, so they cannot establish whether the peer was a
foreign listener or whether the child crashed. This patch fixes that diagnostic
gap; it does not claim to diagnose or repair a production reload defect.

Changed behavior:

- Every boot checks the port before Popen, during readiness, and after the
  identity handshake. `/proc/net/tcp{,6}` listener inodes are matched to process
  descriptors. All reuseport owners are checked. A foreign owner fails with
  PID/cmdline, without another connection attempt; an unreadable live owner also
  fails. The existing SO_REUSEADDR guard still permits TIME_WAIT reuse and does
  not use SO_REUSEPORT.
- Readiness requires the exact listening banner in a newly created log belonging
  to this Popen, INFO Server with `process_id == child.pid`, and PING/PONG on the
  same connection. The banner itself contains no PID. The child must remain alive
  through the handshake. The warmup and recovered GETs reuse that verified
  connection. Empty/stale logs, half-open connections, wrong INFO identities, and
  wrong PING replies cannot establish readiness.
- `server-1.json` and `server-2.json` retain the boot UUID (`run_id`), its explicit
  source, child PID, argv, INFO fields, readiness evidence, exit status, and failure
  details. TomoKV currently has no INFO `run_id`; the harness UUID is labeled
  `persistfix boot UUID`, and `info_run_id` separately records a server run ID if
  one is supplied. No server identity field is fabricated.
- Recovery startup, GET, value assertions, shutdown, and report failures are
  wrapped with status and the last 8192 log bytes. A dead child is reported as
  `recovered server exited N: <log tail>` (negative N means a signal). An empty log
  is explicitly `<empty log>`. A bounded two-second natural-exit wait handles a
  reset preceding waitpid visibility. If the child is still alive, the message
  explicitly says `still running (exit_status=None)`; cleanup SIGKILL is not
  misrepresented as the cause. The original assertion/reason is retained.

Validation executed:

- `taskset -c 112-127 python3 -B tests/persistfix.py --self-test`: 14 tests PASS.
  They cover readiness, both boot guards, PID/cmdline ownership through a real
  socket-only fixture, artifacts, delayed exits, and the actual exercise error
  handler for boot/GET/lost-write/report failures. Popen and network connection
  creation are prohibited by mocks except for explicitly mocked boot calls; no
  executable server is involved.
- `taskset -c 112-127 python3 -B tests/gates_test.py PersistfixWiring TSANWiring`:
  9 tests PASS (including the nested identity tests). The existing TIME_WAIT
  witness, live-listener refusal, eight gate invocation arguments, private artifact
  directories, and unit-job dependency checks remain active.
- Four additional throwaway *harness* negative controls remove the banner check,
  INFO PID check, port-owner check, or error-context wrapper. All four are rejected
  by the self-tests. Sources/logs: `build/persistfix3/no-*.{py,log}`; receipt:
  `build/persistfix3/harness-controls.json`. These supplement the original AOF PRE
  controls; they do not replace them.
- AST comparison verifies all 14 existing assertions in `exercise` are unchanged.
  `build/persistfix3/preservation.json` also records byte-identical `src/`,
  `tests/gate.sh`, the label fixture, `tests/persistfix_checks.py`,
  `tests/persistfix_unit.cc`, and `tools/persistfix_controls.py` against `cd02ecbab`.
- `git diff --check`: PASS.
- `taskset -c 112-127 python3 -B tests/gate_receipt.py --self-test`: PASS, exit 0;
  log `build/persistfix3/receipt-selftest.log`.
- `taskset -c 112-127 python3 -B tests/gates_test.py`: **FAIL**, 62 tests,
  7 failures, 143.262 seconds. All seven failures are in unchanged
  `SchedulerWiring` fixtures: their existing 45-second subprocess deadline returns
  124. The complete suite is not green. No scheduler assertion/deadline was changed
  or failure waived. Log: `build/persistfix3/gates-selftest.log`, with preserved
  `build/scheduler-failure-*` artifact paths. The focused PersistfixWiring/TSANWiring
  suite was rerun after this and passes all 9 tests plus all 14 nested identity
  tests; log `build/persistfix3/wiring-selftest.log`.

The new self-tests are called from the existing `PersistfixWiring` receipt checks.
No gate row was added, removed, or relabeled. All eight labels remain
`AOF in-window {kill,term} recovery ({1s,2s}, {epoll,uring})`.
Quick/full count delta: **0 / 0**. EXPECT_* and the label fixture are untouched.
All pre-existing window, acknowledgement, recovered-value, and persistence report
assertions and PRE controls remain mandatory.

Maintainer live validation requested (not run here):

```sh
for engine in epoll uring; do
  for mode in 2s 1s; do
    for check in kill term; do
      python3 tests/persistfix.py --binary build/tomokv \
        --mode "$mode" --case "$check" --net-io "$engine" \
        --cores 0-7 --ratio 6:2 --port 16379 --count 1024 \
        --artifacts build/persistfix3-live || exit 1
    done
  done
done
tests/gate.sh iteration
```

Repeat the four original live negative controls on disposable data: old-ack/2s/kill
and old-close/2s/term, each with epoll and uring, using the original
`build/persistfix-controls/{old-ack,old-close}/tomokv` binaries and the same
8-core/16-shard/6:2 geometry. The former must fail on the lost marker (with the
SIGKILL-before-post log witness); the latter must fail on
`persistence shutdown must drain` with refusal/backlog evidence. Startup/identity
failures do not count as those negative-control outcomes. Keep all original
serverless PRE controls as well.

The decision is all eight positive rows passing, all four PRE failures remaining
discriminating, and artifacts proving each actual recovered PID. A foreign owner
must fail immediately with PID/cmdline. A reload crash must include its natural
exit status and log tail. No performance measurement, new binary arm, or PAD is
requested: this lane changes tests only and makes no performance claim.
