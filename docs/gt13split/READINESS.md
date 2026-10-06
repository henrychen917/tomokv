# Test-only readiness extraction

`tests/_lib.py::wait_ready` uses one monotonic deadline for the banner, connection,
PING and optional INFO SERVER identity handshake. It returns only after PONG,
with a live supplied child and matching `process_id`. A supplied log must be
freshly created/truncated by its launcher and contain the exact mainline banner
as a complete matching line. Logs/PIDs come from the current spawn, including
`watchlive_gate.sh`'s `$!`; the shell also retains its socket-owner check.

Only startup transport errors/EOF and the exact
`LOADING Redis is loading the dataset in memory` PING error are retried.
Authentication, other application errors, almost-matching LOADING strings,
malformed replies, resource exhaustion, and PID mismatch fail. Every unsuccessful
connection closes. Partial line/bulk reads recalculate the same remaining deadline
before every buffered-reader receive, preventing slow fragments from renewing it.
Successful connections resume the launchers' original application timeouts; no application
command is retried. Mainline still loads before listening and sends no LOADING.
The LOADING controls use mocks exclusively.

Migrated launchers: `_gate_process`, `shutdown_persist`, `resizefix`, `wiredump`,
`mdbqsbr_live`, `connreset_repro`, `servertail`, `signalacct_live`, `flushfix_checks`,
`redisgap`, `reorder_flip`, and `watchlive_gate`. Each owned TomoKV boot supplies its
fresh log and child identity. The wiredump Redis oracle uses its own PONG/INFO
handshake without requiring TomoKV's banner. Existing launch flags and server
startup code are unchanged. Persistfix's stronger readiness logic is unchanged.

Validation (serverless):

- Readiness: original GT13 8 + 12 additional deadline/identity/strict-reply tests.
- Gate process: 12; signalacct harness: 5; connreset harness: 4; mdbqsbr harness: 10.
- Total above: **51 passed**. Existing persistfix self-test: **14 passed**.
- `bash -n tests/gate.sh tests/watchlive_gate.sh`, Python syntax and `git diff --check` pass.

The mdbqsbr failure mock now fails the shared helper, while preserving assertions
that the original diagnostic/log tail reaches the report and the owned child is
reaped. No production source, binary, gate row or EXPECT/ledger fixture change
belongs to this extraction. **Row delta: 0.** Live batteries are not claimed run.
