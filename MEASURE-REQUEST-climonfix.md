SV1 and SV2 are implemented on `cx-climonfix`. Release builds and serverless positive/negative controls are complete. Live recovery, the >64-owner delivery proof, and the 14-cell performance null are for MAINLINE; this lane started no server, benchmark, or gate.

Launch HEAD: `e279aeb4cf08ae2c39f26be679388b872fed4667`. The first repository operation after inspecting the clean worktree was `git fetch origin cpp && git merge --no-edit origin/cpp`; it reported already up to date. Implementation commits: `e0c35fa83`, `b6ad8eb3e`, `2c9c88021`, `8c8a5f010`. Nothing was pushed.

The baseline confirms SV1 at `src/core/server.h:2448`: both membership masks used one relaxed atomic word and `io & 63`. The only delivery filters were `src/cmd/notify.inc:465`, `src/cmd/tracking.cc:373,411`, and `src/cmd/climon.cc:663`. The migration forwarding history was ALSO narrow (`src/core/pubsub_event.h:130`, `src/cmd/tracking.cc:484`, `src/cmd/climon.cc:393`); leaving it narrow would still suppress forwarding to a migrated owner 64 away.

`src/core/climon_mask.h:9` now supplies two-word membership and forwarding operations. Both Server masks use it (`src/core/server.h:2481`), and all four delivery sites and both forwarding sites use `contains(io)`/`add(io)`. All shared mask loads/RMWs retain relaxed ordering. Low words retain their original Server offsets; high words are appended at `server.h:3774`. The event carries both words. No mask read was added to the disarmed operation path.

The baseline confirms SV2 at `src/cmd/server_tail.cc:268` (only explicit SAVE took a snapshot), `src/main.cc:65` (signals immediately stopped workers), and `src/core/config.h:347` (the three default save clauses). The requested configured-save policy and SAVE/NOSAVE overrides agree with the [Redis SHUTDOWN documentation](https://redis.io/docs/latest/commands/shutdown/), including SIGTERM/SIGINT and refusing a failed final save. No signal knobs were added.

Command and signal requests now share `Server::shutdown` (`src/cmd/server_tail.cc:249`). A command samples the live save policy; SAVE and NOSAVE override it. The signal handler (`src/main.cc:66`) only publishes an atomic request while serving. The existing IO save cron (`src/core/server.h:2096`) performs the blocking save while owners remain alive. The request shares the existing cron-arming byte with the configured-save bit, so CONFIG SET save cannot erase a concurrent signal request, including when save is disabled. The signal handoff adds no timer or per-operation check; it uses the existing one-second cron and bounded parks. Interrupted boot retains the original immediate teardown.

A second shutdown hazard was closed: ordinary blocking SAVE owners drain queued post-cut writes before file finalization. Stopping after that SAVE could lose newly acknowledged writes. Shutdown snapshots instead hold finished owners (`src/core/ex_loop.h:2052,2121`), and successful file finalization publishes all stop flags before releasing the epoch (`src/snapshot/snapshot.cc:665`). Failure releases the holds and resumes service. A new snapshot acquires Idle before checking outstanding holds (`snapshot.cc:195`), so it cannot publish an epoch to owners still leaving a failed shutdown save. The hold check must follow the phase CAS: sampling it first permits an intervening epoch to acquire a hold and fail before that CAS.

A required save that reports Busy or Failed never authorizes a stop. Commands return the existing shutdown-error prefix; signal requests retry Busy from cron and report Failed while keeping the server running. In particular, command SHUTDOWN now refuses a concurrent snapshot/placement transition instead of silently exiting without the requested save. Existing NOW/FORCE/ABORT parsing is unchanged; this does not claim broader compatibility for those pre-existing options. Snapshot headers, frames, serializers and version are unchanged. AOF shutdown defects PS1/PS2 remain the persistfix lane's work.

All eight layout locks compile in the directed unit: Op 336, Client 1984, ThreadCtx 1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. Both production database variants build. No changes to `io_loop.h`, `wb.h`, or `reorder.cc`; the conditional wbland witness requirement is therefore not triggered.

Serverless checks ran only on CPUs 112–127. These reproduce the local checks without booting a server:

```bash
taskset -c 112-127 make -j16 BUILD_ROOT=build/climonfix-post all \
  build/climonfix-post/shutdown-unit build/climon-mask-unit build/climon-mask-old-unit
taskset -c 112-127 ./build/climon-mask-unit
taskset -c 112-127 ./build/climonfix-post/shutdown-unit
taskset -c 112-127 python3 tests/climonfix_artifacts.py controls
taskset -c 112-127 python3 tests/climonfix_artifacts.py armed
taskset -c 112-127 bash -n tests/gate.sh
taskset -c 112-127 python3 -m py_compile \
  tests/shutdown_persist.py tests/climon_128.py tests/climonfix_artifacts.py
```

Positive output:

```text
climon mask tracking: PASS (64 owner pairs, both disarm directions)
climon mask monitor: PASS (64 owner pairs, both disarm directions)
Errors trying to SHUTDOWN: injected snapshot refusal; server remains running
shutdown policy, signal handoff, failure and owner hold: PASS
```

The error line is the injected failure case. The shutdown fixture has 16 shards and 6 IO + 2 EX logical owners, with unopened Rings and no worker loops. It invokes the registered SHUTDOWN handler and real signal-request/cron policy. Only snapshot disk IO is wrapped for the policy cases. The hold test calls the REAL snapshot admission method and verifies it refuses before touching a ring; the finalization test calls the REAL successful-file completion method and asserts every owner stops.

Each negative control runs a throwaway serverless copy, with a named assertion and exit 1. No corrupted server was run against any data:

| Reverted mechanism | Observed failure assertion |
|---|---|
| Mask word selection restored to word 0 | `disarm retains the other owner at distance 64` |
| Configured shutdown save removed | `default SHUTDOWN saves before stop` |
| Signal request restored to immediate-stop fallback | `signal leaves owners alive for final save` |
| Shutdown owner hold removed | `held owner prevents admission of another snapshot` |
| Stop publication removed from file completion | `successful finalization publishes stop before releasing epoch` |

Evidence: `build/climon-mask.log`, `build/climon-mask-old.log`, `build/shutdown-unit.log`, `build/climonfix-controls.log`, `build/climonfix-controls.json`; individual negative builds/logs are under `build/climonfix-control-*`. The mask gate row builds and checks its negative control as well as the positive binary.

Offline PRE/POST receipts:

| Check | PRE | POST | Result |
|---|---:|---:|---|
| climon armed gate, `tomo` | 211 bytes | 211 bytes | Identical after relocation normalization |
| climon armed gate, `tomo_db0` | 211 bytes | 211 bytes | Identical after relocation normalization |
| Generic command bodies | 16 | 16 | 16/16 identical |
| Broad existing off-path inventory | 368 | 368 | 342/368 identical; NOT a whole-path NULL |
| `.text` | 7,554,449 bytes | 7,556,081 bytes | +1,632 bytes |

The armed gate still reads `climon_armed_cached_` with one `mov 0x1b40(%rdi),%r12d`, then tests it and returns on zero. Evidence: `build/climonfix-armed-audit.json`. The broader audit is `tests/r7shadow_noop.py PRE POST build/climonfix-byte-audit --inventory wbrule`, run pinned to 112–127; it intentionally returns 1 because 26 bodies differ. Category receipts: commands 16/16, dispatch 52/56, envelope 178/184, multi-key commands 30/32, retire 16/16, scheduler 50/64 identical. Full diffs and final binary hashes are in `build/climonfix-byte-audit/audit.json`. No generic performance-null claim is made from the partial byte audit.

The binaries below are ready. PRE was built from launch HEAD before any source edits; do not rebuild its directory from the current source tree. Build logs are `build/climonfix-pre/build.log`, `build/climonfix-post.log`, and `build/climonfix-post-final.log`.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/climonfix-pre/tomokv` | `a935ce982dd2c43e63b4d0b440c765c54c20d828eec73c549282c4d7512cb73c` |
| POST | `build/climonfix-post/tomokv` | `d9e61ecfcf0614c5f624f897b8c5f159095341c0843e67d3aee2379cdf5a291d` |
| PAD A | `build/climonfix-pad/tomokv` | `1ac279e4b28d3754461cfc3d3313837a6aca15619f9d6f7397b9a047013b0136` |

PAD is kind **A, behaviour twin**: PRE mask and shutdown behavior, with POST's data layout and total `.text` size (7,556,081 bytes). Its link-only, unexecuted padding is 768 bytes. Individual function addresses differ, so it is not an exact text-address twin; the paired null is required. Source and build are in `build/climonfix-pad-src`, metadata in `build/climonfix-pad/kind.json`; `taskset -c 112-127 python3 tests/climonfix_artifacts.py pad` reproduces it. There is no runtime PAD knob.

MAINLINE live SV2 proof, at the gate's 16-shard, 6:2 geometry. The script owns each process, verifies its PID and mode, starts from a fresh directory, proves no periodic snapshot captured the witness first, then restarts and checks the acknowledged key. Command cases include default save, NOSAVE preserving an older snapshot while losing the new key, explicit SAVE with save disabled, boot/runtime save changes, and failed-save continued service. Signal cases also test save disabled. Run both network engines and thread modes:

```bash
cd /home/user/Projects/cx-climonfix
SV2_RUN=$(mktemp -d "$PWD/build/sv2-live.XXXXXX")
for MODE in 1s 2s; do
  for NET in uring epoll; do
    taskset -c 8-15 python3 tests/shutdown_persist.py \
      --binary build/climonfix-post/tomokv --cores 0-7 --ratio 6:2 \
      --port 17991 --mode "$MODE" --net-io "$NET" --case all \
      --output "$SV2_RUN/$MODE-$NET" || exit 1
  done
done
```

For live negative controls, run the following on PRE in fresh directories. Each must exit nonzero at the recovery assertion, not merely time out or fail to boot:

```bash
SV2_OLD=$(mktemp -d "$PWD/build/sv2-old.XXXXXX")
for STOP_CASE in command sigterm sigint; do
  if taskset -c 8-15 python3 tests/shutdown_persist.py \
      --binary build/climonfix-pre/tomokv --cores 0-7 --ratio 6:2 \
      --port 17991 --mode 2s --case "$STOP_CASE" \
      --output "$SV2_OLD/$STOP_CASE" >"$SV2_OLD/$STOP_CASE.log" 2>&1; then
    echo "unexpected PRE pass: $STOP_CASE"; exit 1
  fi
  NAME=$STOP_CASE
  [ "$STOP_CASE" != command ] || NAME=default
  grep -F "$NAME: acknowledged write recovered after restart (got None)" \
    "$SV2_OLD/$STOP_CASE.log" || exit 1
done
```

MAINLINE live SV1 proof needs more than 64 physical IO owners, which does not fit the lane's 112–127 CPU allocation. In one terminal start this disposable, foreground 112-owner 1s server; leave client balancing at its default 1:

```bash
cd /home/user/Projects/cx-climonfix
SV1_DATA=$(mktemp -d "$PWD/build/sv1-data.XXXXXX")
taskset -c 0-111 ./build/climonfix-post/tomokv \
  --thread-mode 1s --shards 16 --bind 127.0.0.1 --port 17992 \
  --dir "$SV1_DATA" --save '' --enable-debug-command yes --client-lb 1
```

After its ready line, in another terminal:

```bash
cd /home/user/Projects/cx-climonfix
taskset -c 112-127 python3 tests/climon_128.py 127.0.0.1 17992
redis-cli -h 127.0.0.1 -p 17992 SHUTDOWN NOSAVE
```

The driver discovers and rechecks owners i/i+64, proves both trackers first received invalidations, then disarms the high owner. It checks ordinary writes, flush delivery, and expiry notifications plus the invalidation counter. Geometry movement before the window causes a bounded fresh-state re-arm; once the window is witnessed, missing delivery fails. Exhausting either bound fails, never skips. Repeat the foreground boot using `build/climonfix-pre/tomokv` and a NEW empty directory: the driver must fail at `write: disarm retains delivery to owner i: invalidation missing`. MONITOR and both clear directions are covered by the serverless production-mask test.

Eight rows were added. Counted by LINE relative to the quick exit at `tests/gate.sh:2906`: the mask row is at 1240 (+1), shutdown policy at 1252 (+1), and the live row at 1261 is inside 2 modes × 3 stop cases (+6). The family is scheduled before that exit. Thus **EXPECT_QUICK should become 454 (446+8), EXPECT_FULL 471 (463+8)**. Both constants remain untouched at lines 261–262. The maintainer must update them and the reviewed ledger before accepting a gate result. The gate's live rows cover both modes on uring; the standalone command above also covers epoll.

After that owner update, the exact iteration command is:

```bash
tests/gate.sh iteration --candidate-binary "$PWD/build/climonfix-post/tomokv" \
  --reference-binary "$PWD/build/climonfix-pre/tomokv"
```

MAINLINE performance request: the unchanged 14 generic cells in `tests/wbhybrid2_cells.txt`, PRE versus POST and PRE versus PAD A. The decisive result is no repeatable regression at matched offered load relative to the same-binary null. Record rate/latency, cycles/op, instructions/op, and IPC per arm; instructions alone are not the verdict. An inconsistent identical-arm run is an instrument failure, not evidence of a null.

| Cells | PRE | POST | PAD A |
|---|---|---|---|
| h05, h06, p8g, p8s | Not run | Pending mainline | Pending mainline |
| d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0 | Not run | Pending mainline | Pending mainline |
| d32g_l1, d8s_l1, d32s_l1, x9_32_l1, x9_32_l0 | Not run | Pending mainline | Pending mainline |

The gate instrument can collect the same-binary control and both comparisons serially with these commands. Null collection deliberately exits 3 for PARTIAL; require its `null_control.verdict` to be PASS. Do not count that exit alone as success:

```bash
MR_RUN=$(mktemp -d "$PWD/build/climonfix-abba.XXXXXX")
COMMON=(--cells tests/wbhybrid2_cells.txt --subset full --build-reference 0 \
  --server-cores 0-7 --server-smt '' --load-cores 8-111 --load-smt '' \
  --ports 17993-17998)
NULL_RC=0
python3 tests/abbagate.py "${COMMON[@]}" --collect-null 1 \
  --candidate-binary build/climonfix-pre/tomokv \
  --reference-binary build/climonfix-pre/tomokv --output "$MR_RUN/null" || NULL_RC=$?
[ "$NULL_RC" -eq 3 ] || exit 1
python3 - "$MR_RUN/null/results.json" <<'PY'
import json, sys
result = json.load(open(sys.argv[1]))
assert result['null_control']['verdict'] == 'PASS', result['null_control']
PY
for ARM in post pad; do
  python3 tests/abbagate.py "${COMMON[@]}" \
    --candidate-binary "build/climonfix-$ARM/tomokv" \
    --reference-binary build/climonfix-pre/tomokv \
    --null-result "$MR_RUN/null/results.json" --output "$MR_RUN/$ARM" || exit $?
done
```

These live commands were written, not executed. Results belong in `MEASURE-RESULT`; there is no live performance or restart claim yet.

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat` (including this report):

```text
 MEASURE-REQUEST-climonfix.md | 198 +++++++++++++++++++++++++++++++++++++++++++
 Makefile                     |  14 +++
 src/cmd/climon.cc            |  15 ++--
 src/cmd/notify.inc           |   5 +-
 src/cmd/server_tail.cc       |  90 +++++++++++++-------
 src/cmd/tracking.cc          |  21 +++--
 src/core/climon_mask.h       |  33 ++++++++
 src/core/ex_loop.h           |  23 ++++-
 src/core/pubsub_event.h      |   3 +-
 src/core/server.h            |  64 +++++++++++---
 src/main.cc                  |   7 +-
 src/snapshot/snapshot.cc     |  12 ++-
 src/snapshot/snapshot.h      |   4 +-
 tests/climon_128.py          | 109 ++++++++++++++++++++++++
 tests/climon_mask_unit.cc    |  49 +++++++++++
 tests/climonfix_artifacts.py | 165 ++++++++++++++++++++++++++++++++++++
 tests/gate.sh                |  37 +++++++-
 tests/shutdown_persist.py    | 158 ++++++++++++++++++++++++++++++++++
 tests/shutdown_unit.cc       | 161 +++++++++++++++++++++++++++++++++++
 19 files changed, 1092 insertions(+), 76 deletions(-)
```
