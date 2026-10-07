# shutsave — terminal shutdown during SAVE

Implemented and committed on `cx-shutsave`, in `/home/user/Projects/cx-shutsave`.
Production changes are confined to `src/cmd/multidb.cc` and
`src/snapshot/snapshot.cc`. **42/42 serverless shutdown controls and 36/36 Python
controls pass.** The existing shutdown policy unit also passes. No server,
benchmark, wire battery, or gate was run, and nothing was pushed.

PRE is merge-base `6a3c90acb9f811a569b7bbe6358fb8f69199b214`, built before edits.
The initial merge fast-forwarded from `cce87ae77`; fetching and merging `origin/cpp`
again immediately before the final proof reported already up to date at that same
merge-base. Implementation commits: `57b1360b1`, `5b7086d16`, `da9c01f0a`,
`68fd3cd7f`. The final commit archives this report and the receipts.

The requested `/home/user/Projects/cx-flakefix3/build/flakefix3/live-mainline/psfix.log`
is absent here, as is that worktree directory. Its lines 100–180 could not be read.
The 3/4 live result, `polls=3840`, client TimeoutError, and original `elapsed_ms=2703`
are the maintainer's supplied incident evidence, not observations made by this lane.
The landed climonfix reports and `MEASURE-REQUEST-flakefix3.md` were read.

## Failure mechanism and correction

At eight physical participants, `DatabaseMap::grace_bound_ms()` is
`2 * 50 ms * (8 + 1) = 900 ms`. `join_workers()` previously aborted after three
graces, or 2700 ms. Its predicate is the physical workers' **exited** count.
`stage=0 request=0` does not imply an outstanding SWAPDB/map publication: the
database-map lifetime supervisor also owns the ordinary shutdown wait.

On the failing harness's `--save ''` boot, SIGTERM immediately publishes terminal
stop flags. A synchronous SAVE could continue waiting for ready/frozen/finished
snapshot acknowledgements from executors that had already stopped. With AOF
enabled, the saving IO worker also cannot reach AOF's `execution_stopped`
rendezvous; the other AOF workers wait there before their database lifetime guards
can report exit. This is a source-established schedule explaining all eight
`exited=0 stop=1` participants; the missing original log supplies no stack trace.
Merely increasing the 2700 ms watchdog would not remove that stopped-producer wait.

`SnapshotManager::start()` now checks terminal shutdown at its existing cold
coordination/capture waits, including immediately after the atomic-group drain.
It marks the epoch Failed, reaps its own outstanding io_uring requests, closes and
unlinks the temporary file, and returns failure without demanding acknowledgements
from stopped producers. Failed completions cannot resubmit writes or advance to
rename. Owner state and queued chunks remain owned until teardown after joins.
The previously completed snapshot stays valid. A finalization already in its
filesystem call may instead finish and publish a complete, valid file.

The database watchdog grants active snapshot/rewrite work
`max(ordinary_bound, Server::kShutdownSaveWaitNs / 1e6)`. This is **10 seconds at the
requested eight-worker geometry**. Shutdown latches that allowance until workers
leave their save stacks, and never restarts the original stop timestamp. A stuck
snapshot still triggers the worker fatal at the ten-second predicate; a worker
without persistence retains its ordinary 2700 ms grace. The supervisor's existing
50 ms polling and scheduling latency still apply. As in climonfix3, this is a
coordination bound, not asynchronous cancellation of arbitrary kernel filesystem IO.
Existing larger-geometry ordinary bounds are not shortened by this change.

The cold `DatabaseMap::State` records the last persistence observation. Live
retirement/drain supervision also uses the bounded allowance, including one
ordinary opportunity after persistence was last observed. This does not acknowledge
a participant, free a map early, or reset a retirement's absolute age.

The addendum's live-command concern has two distinct outcomes:

- SWAPDB, including transactional SWAPDB, cannot start a namespace drain during
  an active snapshot: admission shares the shape mutex and checks snapshot state.
  The serverless boundary control verifies refusal through Preparing, Freeze,
  Mark, Capture and Failed, then admission after Idle.
- A map **already retired before SAVE begins** can still be waiting for that
  saving participant's true safe point. PRE's live retire watchdog does abort
  this schedule. The new grace covers it, and the control requires real subsequent
  acknowledgements before reclamation. FLUSHDB and MOVE do not publish a database
  map or start the SWAPDB namespace-drain timer; their participation in an existing
  retired-map grace has the same protection. No reader registration, retries,
  seqlock, write ownership rule, or per-operation hook was introduced.

The new terminal-stop fixtures use the incident's disabled save schedule.
`SHUTDOWN` there therefore requests no final save, as does `SHUTDOWN NOSAVE`.
Configured-saving SHUTDOWN retains climonfix's Busy refusal during an older snapshot;
configured signals retain its retry/final-save policy. The existing shutdown unit
still verifies configured/default saving, overrides, Busy/failure refusal, the
ten-second shutdown-save coordination timeout, and post-cut owner holds.

## GT19 client correction

`tests/_save_timeout.py` supplies a SAVE-only socket budget:
`30 seconds + bytes / (8 MiB/second)`. A 512 MiB value image gets 94 seconds.
The differential generator reads each peer's `INFO memory` / `used_memory`, so
its budget also includes key/allocator overhead, and logs the chosen timeout.
The socket's previous timeout is restored on success and failure.

The outer psfix process watchdog includes four synchronous saves, all twelve
ten-second idle barriers, and setup time, using the larger peer's memory footprint.
The standalone successful SAVE retry and AOF rewrite completion wait also scale
with the seeded dataset. The no-load process/rewrite defaults remain 90/15 seconds.

The both-peer idle barrier remains ten seconds with 1 ms polls. The two SAVE plus
one BGSAVE operations per peer, both exact `rdb_saves == before + 1` observations,
failed-save unchanged count, and exact rewrite/save counter assertions all remain.
The real generator control rejects both a +2 save increment and restoration of
the old 30-second SAVE timeout. The load proof still fails unless its first
before-target-SAVE barrier witnesses both peers' independent background jobs.

## Executed serverless proof

All execution/build affinity stayed within CPUs 112–127. The new snapshot matrix
uses 112–119: both modes have eight owners; split is 6 IO + 2 EX, 16 shards,
16 databases, atomic 1. Fixtures invoke real snapshot/executor progress hooks and
registered handlers, with no listener or worker loop. The finalization case adds
one supervisor thread running real `join_workers()`.

| Proof | PRE control | POST result |
| --- | --- | --- |
| Persistence finishes at virtual 8 s, worker leaves after old 2.7 s bound | Worker fatal | PASS, snapshot and rewrite |
| Permanently stuck snapshot at shutdown | — | Fatal at `elapsed_ms=10000` |
| Stuck worker with no snapshot/rewrite | — | Ordinary fatal, sampled at 3000 ms |
| Retired map held by SAVE for 3 s | Live retire fatal | PASS; retained until real acknowledgements |
| Retired map remains held beyond persistence deadline | — | Live retire fatal at sampled 11000 ms |
| 512 MiB SAVE, terminal SIGTERM request during real Capture | Worker fatal, all eight `ack=0 exited=0 stop=1` | PASS, clean abandonment |
| 512 MiB BGSAVE, shutdown inside real file finalization | Worker fatal | PASS, complete file validates |
| SAVE during Preparing / Freeze / Mark, stopped producers | — | PASS in both modes |
| SWAPDB admission during snapshot | — | PASS, no premature drain timer |

The 512 MiB matrix exercises **each of SIGTERM request, SHUTDOWN NOSAVE, and
SHUTDOWN**, in both modes: normal-file SAVE, normal-file BGSAVE abandonment,
normal-file BGSAVE finalization, and real io_uring SAVE cancellation. All 24 cases
pass. They insert 131072 actual 4096-byte values using registered SET handlers.
Capture cancellation requires a real written frame, and io_uring cancellation
requires zero outstanding writer requests before return. The original snapshot
must remain byte-identical and loadable, and temporary files must be removed.

Finalization parks the actual fdatasync call until the supervisor's virtual clock
reaches 8 s, then executes real fdatasync/rename and validates the complete snapshot
with `snapshot_read_plan()`. Only the supervisor clock is virtual; this is not a
wall-time measurement or a wire-process exit receipt. The separately stalled
controls prove the ten-second predicate cannot become unbounded. PRE is linked
from its frozen production objects against the same current fixture, not a
source mutation of POST.

Receipts: [42 schedules and exit statuses](docs/shutsave/controls.json),
[individual outputs](docs/shutsave/control-logs.txt.gz), and
[validation log](docs/shutsave/validation.log). Python totals are differ 24,
psfix 7, live-driver guard controls 5. The driver controls reject missing windows,
an unrelated PRE fatal, a clean PRE exit, and exhausted fresh-state arming.

Reproduce the serverless work, keeping the frozen PRE directory intact:

```bash
taskset -c 112-127 make -j16 BUILD_ROOT=build/shutsave/POST \
  all build/shutsave/POST/shutsave-unit build/shutsave/POST/shutdown-unit
taskset -c 112-119 python3 tools/shutsave_artifacts.py
taskset -c 112-119 build/shutsave/POST/shutdown-unit
taskset -c 112-127 python3 tests/differ_test.py -v
taskset -c 112-127 python3 tests/psfix_test.py -v
taskset -c 112-127 python3 tests/shutsave_test.py -v
taskset -c 112-127 python3 tools/psfix_artifacts.py \
  build/shutsave/PRE build/shutsave/POST build/shutsave/audit
taskset -c 112-127 python3 tools/shutsave_audit.py
taskset -c 112-127 python3 tools/shutsave_pad.py
```

## Instruction, byte and layout audit

Across both database namespaces, **1223/1223 emitted command bodies are raw-byte
identical, with equal relocation targets**. This includes all 1211 bodies called
ordinary by the existing PSFIX audit and the twelve CONFIG/INFO bodies it excludes.
All **1492/1492 tracked parser/dispatch/storage/scheduler hot bodies** likewise have
identical raw bytes and targets. There are 17009 compared function pairs, 21 changed
cold bodies, and no added/removed bodies in the paired production objects.

[Every changed body, PRE/POST byte and instruction counts, and its reviewed reason](docs/shutsave/instructions.log)
is listed explicitly; [the complete machine-readable audit](docs/shutsave/audit.json.gz)
also includes raw hashes and layouts. Changes are snapshot start/its cancellation
lambda/exception cleanup, its cold completion helper's compiler inlining, database
watchdog/join/reclaim logic, and cold State construction/destruction/condition-variable
offsets. Opcode and callee mutation controls both fail the audit as required.
No compile-budget override was introduced or adjusted.

All eight locked layouts and every existing field offset checked by the artifact
tool are equal. Only separately allocated cold `DatabaseMap::State` grows:
192 -> 200 bytes. PRE `.text` is 7,811,749 bytes; POST is 7,812,565 (+816).

PAD is **kind A, behaviour twin**: PRE behavior with POST's exact cold State
layout and total `.text` size. It adds 784 unexecuted padding bytes. Individual
function addresses may differ; this is not an exact-address twin. Its serverless
join control reproduces PRE's fatal. [PAD construction receipt](docs/shutsave/pad-kind.json).
No throughput/IPC null is claimed from the byte proof.

| Arm | Binary | SHA-256 |
| --- | --- | --- |
| PRE | `build/shutsave/PRE/tomokv` | `316a4ff72e08bdcaf0cee98f646e34748d16d3ec59eb9c3ba29a0d1f63291307` |
| POST | `build/shutsave/POST/tomokv` | `f9fa6b925957f8c421377a166e6a55b8ee95dc986746fec34cf7b0899e221f17` |
| POST copy | `build/tomokv` | `f9fa6b925957f8c421377a166e6a55b8ee95dc986746fec34cf7b0899e221f17` |
| PAD A | `build/shutsave/PAD/tomokv` | `1a4ec753a58861de81b92ff40592896344cc21e06168e519421d7871d6d2b220` |

`cmp` confirms the two POST paths contain the same bytes. Build logs and source
provenance are archived in [build logs](docs/shutsave/build-logs.txt.gz) and
[provenance](docs/shutsave/provenance.json). Python compilation and `git diff --check`
pass. The [grep audit](docs/shutsave/text-audit.json.gz) covers 210 raw, decoded,
JSON and escaped spellings of changed string literals throughout `tests/`.

**Gate rows: +0 quick / +0 full.** `tests/gate.sh` is byte-identical to merge-base.
No declarations or collections were added on either side of its quick exit at
line 3361. EXPECT_QUICK/EXPECT_FULL remain the maintainer's 500/517 at lines 279–280.

## Mainline wire and stress proof — NOT RUN here

Run serially on the scheduled quiet box. The wire driver observes a written
temporary-file prefix before sending the stop, uses a different IO owner for the
command, enforces exit 0 within 10 wall-clock seconds, and restarts with AOF disabled
to validate the actual snapshot. It accepts a complete image or the valid old image,
with exact key counts. Missing windows retry on three fresh datasets and then fail.

```bash
set -euo pipefail
cd /home/user/Projects/cx-shutsave
sha256sum -c docs/shutsave/SHA256SUMS
SHUTSAVE_LIVE=$(mktemp -d "$PWD/build/shutsave/live.XXXXXX")
for MODE in 2s 1s; do
  for NET in uring epoll; do
    for OPERATION in SAVE BGSAVE; do
      for ACTION in sigterm nosave shutdown; do
        taskset -c 120-127 python3 tests/shutsave.py \
          --binary build/shutsave/POST/tomokv --cores 112-119 --port 18340 \
          --mode "$MODE" --net-io "$NET" --operation "$OPERATION" --action "$ACTION" \
          --root "$SHUTSAVE_LIVE/$MODE-$NET-$OPERATION-$ACTION"
      done
    done
  done
done
taskset -c 120-127 python3 tests/shutsave.py \
  --binary build/shutsave/PRE/tomokv --cores 112-119 --port 18340 \
  --mode 2s --net-io uring --operation SAVE --action sigterm --expect-pre-fatal \
  --root "$SHUTSAVE_LIVE/PRE-fatal"
taskset -c 120-127 python3 tests/psfix.py \
  --binary "$PWD/build/tomokv" --oracle /home/user/Projects/redis74/src/redis-server \
  --root "$SHUTSAVE_LIVE/psfix" --port 18340 --cores 112-119 --load-cores 120-127 \
  --mode 2s --databases 16 --atomic 1 --seeds 7 28 --repeats 6 \
  --bgsave-load-keys 131072 > "$SHUTSAVE_LIVE/psfix.log" 2>&1
sha256sum -c docs/shutsave/SHA256SUMS
```

The PRE wire control must contain the specific worker-shutdown fatal; an unrelated
error, unarmed window, or clean exit fails that control. Actual SIGTERM delivery and
real process exit statuses belong to this pending wire proof, not the serverless
signal-request simulation above.

| Repeat | Seed 7 RESP2 | Seed 7 RESP3 | Seed 28 RESP2 | Seed 28 RESP3 |
| --- | --- | --- | --- | --- |
| 1 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 2 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 3 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 4 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 5 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| 6 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

Acceptance requires all 24 differential legs PASS, every first before-target-SAVE
barrier witnessing `busy_peers=target,oracle`, and all exact counter checks. Keep
the arming logs; exhaustion is failure. Append actual results as `MEASURE-RESULT`.

## Mainline 14-cell null — NOT RUN here

Use the unchanged cells in `tests/wbhybrid2_cells.txt`: h05, h06, p8g, p8s,
d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1,
x9_32_l1, x9_32_l0. Collect PRE/PRE first, then PRE/POST and PRE/PAD A.

```bash
SHUTSAVE_ABBA=$(mktemp -d "$PWD/build/shutsave/abba.XXXXXX")
COMMON=(--cells tests/wbhybrid2_cells.txt --subset full --build-reference 0 \
  --server-cores 0-7 --server-smt '' --load-cores 8-111 --load-smt '' --ports 18350-18355)
NULL_RC=0
python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 \
  --candidate-binary build/shutsave/PRE/tomokv --reference-binary build/shutsave/PRE/tomokv \
  --output "$SHUTSAVE_ABBA/null" || NULL_RC=$?
test "$NULL_RC" -eq 3
python3 - "$SHUTSAVE_ABBA/null/results.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
assert result['null_control']['verdict'] == 'PASS', result['null_control']
PY
for ARM in POST PAD; do
  python3 tests/abbagate.py "${COMMON[@]}" \
    --candidate-binary "build/shutsave/$ARM/tomokv" --reference-binary build/shutsave/PRE/tomokv \
    --null-result "$SHUTSAVE_ABBA/null/results.json" --output "$SHUTSAVE_ABBA/$ARM"
done
```

| Comparison | Matched-load rate/latency | Cycles/op | Instructions/op | IPC |
| --- | --- | --- | --- | --- |
| PRE/PRE, 14 cells | Pending | Pending | Pending | Pending |
| PRE/POST, 14 cells | Pending | Pending | Pending | Pending |
| PRE/PAD A, 14 cells | Pending | Pending | Pending | Pending |

The verdict is no repeatable matched-load regression beyond the valid same-binary
null; cycles/op, instructions/op and IPC explain the result together. These receipts
and the full `tests/gate.sh iteration` remain mainline's acceptance work.
