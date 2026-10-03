**atomfix — AT1 / AT2 correctness handoff, 2026-10-03**

Worktree `/home/user/Projects/cx-atomfix`, branch `cx-atomfix`. Launch HEAD:
`e279aeb4cf08ae2c39f26be679388b872fed4667`. Ran `git fetch origin cpp && git merge --no-edit origin/cpp`
first; already up to date. Implementation/test commits: `a099925c0`, `be75f63ec`, `2460e6bea`.
Nothing pushed. No server, load generator, benchmark, or gate was run. All builds and executed
serverless checks were pinned to CPUs 112–127.

AT1 and AT2 are confirmed by production-code interleavings, with successful POST checks and
ten named assertion failures in a throwaway PRE control. Live races and both thread-mode boots
remain for mainline. The gate constants deliberately remain **446 / 463**; mainline must change
them to **448 / 465** before expecting a green gate with these two new rows.

The scope is section C, AT1/AT2 in `/home/user/Projects/round3-read/server-atomics.md` and TIER 0
in `/home/user/Projects/round3-read/REGISTER.md`. The caller audit found **six calls, five needing
correction**. `multi.inc:1024` directly sets its store context; it is the compliant model, not a
seventh call to `begin_plain_version`.

| Current source anchor | Writer | Previous cut | Delivered cut |
|---|---|---|---|
| `src/cmd/scatter_engine.inc:3103` | LMPOP/ZMPOP phase two | `state.atomic_pop ? UINT64_MAX : state.snapshot` | `UINT64_MAX` |
| `src/cmd/scatter_engine.inc:3137` | General phase-two writes, including SMOVE/LMOVE/RPOPLPUSH | `state.snapshot` | `UINT64_MAX` |
| `src/cmd/scatter_engine.inc:3308` | Non-atomic MSET | `state.snapshot` | `UINT64_MAX` |
| `src/cmd/scatter_engine.inc:3343` | Non-atomic DEL/UNLINK | `state.snapshot` | `UINT64_MAX` |
| `src/cmd/blocking.inc:623` (call at 628) | Selected blocking-pop execution/resume | `server.atomic_snapshot()` | `UINT64_MAX` |
| `src/cmd/atomics_glue.inc:1018` | Ordinary routed single-key writes | `UINT64_MAX` | Already correct |

AT1: `scatter_engine.inc:1881` decides whether PREPARE needs a snapshot while EXEC activity is
live; EXEC force-admits at either atomic setting (`multi.inc:1576`). Phase-two RMWs used that
old cut to materialize a clone. `begin_plain_version` subsequently assigns the clone a fresh
ticket (`atomics_glue.inc:79`), so the resolver's ticket ranking makes the stale contents win
over acknowledged newer contents (`flatstore_atomic.inc:1064`, especially its `consider` lambda).
The directed tests retain a PREPARE cut, acknowledge an intervening write, then execute the real
phase-two owner handlers. They expose actual lost members, not merely a counter increment.
DEL/UNLINK also returned the wrong count when the stale cut excluded a newly committed key;
the extra audited callers are covered, with MSET checked through the zero-counter contract.

AT2: `Server::atomic_snapshot()` is the safe watermark (`server.h:2715–2780`), not the newest
committed ticket. A concurrent reservation can hold it below an acknowledged push. The old
blocking caller cloned absence, installed a newer tombstone, and returned Missing; its caller
then re-registers the waiter (`blocking.inc:1098`). The serverless witness holds a real commit
bracket, acknowledges the push, executes `blocking_run_direct`, and checks both the returned
element and the unconsumed element. It also reads at the old cut and proves that the immutable
absent predecessor remains absent.

The production changes are the five cut expressions plus a bug counter in
`atomics_glue.inc:32`. Every call is a write path; `snapshot != UINT64_MAX` increments
`g_plain_stale_cuts`. `DEBUG ATOMIC-PLAIN-STALE-CUTS` returns the total (`t_server.cc:1059`), under
the existing DEBUG permission gate. There is no reset that could hide an earlier violation.
Compliant calls perform no counter RMW and allocate nothing. The counter is outside locked
structures; no new configuration knob or delay mechanism was added. Blocking cleanup still uses
the safe watermark. Scatter read cuts and all transaction publication/order gates are unchanged.

The resumed pop may use the newest **committed** value under the owner's stall doctrine in
`/home/user/.claude/projects/-home-user-Projects/memory/tomokv-atomics-stall-doctrine.md`:
it mutates one selected key on that key's owner, rather than assembling a multi-key read from
different cuts. The resolver still excludes foreign undecided/aborted versions
(`flatstore_atomic.inc:1091–1121`). A committed group's shared epoch is visible only after its
installs are complete. Reading the newest version of this one key therefore cannot expose a
partial group. Older readers retain their immutable versions, and this change does not advance
their read cuts or the global safe watermark. Existing same-connection dispatch/RYOW gates still
apply. Waiting for an unrelated foreign reservation to release the safe watermark would impose
cross-client ordering without protecting a torn-read or session hazard; the doctrine permits
the selected pop to consume the completed push now.

**Recorded serverless proof** (`build/atomfix-proof.log`; final rerun after the test edits):

| Case | PRE (five old cuts, new counter retained) | POST |
|---|---|---|
| SMOVE, atomic 0 | Exit 1: `AT1: SMOVE preserves the acknowledged destination write` | PASS |
| LMOVE, RPOPLPUSH, LMPOP, ZMPOP, atomic 0 | Each exits 1: `AT1: phase-two RMW preserves the acknowledged write` | All PASS |
| MSET, atomic 0 | Exit 1: `plain write stale-cut counter is zero` | PASS |
| DEL, UNLINK, atomic 0 | Each exits 1: `DEL/UNLINK counts the newest committed key` | Both PASS |
| Blocking resume, atomic 0 | Exit 1: `AT2: resumed pop consumes the acknowledged wake push instead of re-parking` | Six pop variants PASS |
| Blocking resume, atomic 1 | Same named assertion, exit 1 | Six pop variants PASS |

POST output:

```text
POST plain_0: exit=0
  PASS AT2 six blocking pop kinds, atomic=0
  PASS AT1 SMOVE
  PASS AT1 LMOVE
  PASS AT1 RPOPLPUSH
  PASS AT1 LMPOP
  PASS AT1 ZMPOP
  PASS AT1 MSET
  PASS AT1 DEL
  PASS AT1 UNLINK
PASS plain_0
POST plain_1: exit=0
  PASS AT2 six blocking pop kinds, atomic=1
PASS plain_1
```

Existing serverless `write_latest`, `rename_overlay`, `script_apply`, and `post_apply_probe`
also passed (exit 0). Python syntax, `bash -n tests/gate.sh`, and `git diff --check` passed.
The full build passed all existing layout static assertions: Op 336, Client 1984, ThreadCtx
1408, Shard 1440, FlatStore 944, Rob<64> 192, AtomicEntry 144, Config 624. No locked layout
changed, so no PAD arm is requested. This is a correctness change; no performance claim is made.
The unit build emits the existing harness's allocator `-Wmismatched-new-delete` warnings.

`tests/atomic_plain_checks.inc` extends the existing real-owner harness; it opens no sockets or
workers. `tests/atomic_plain.py` supplies the live races using the geometry and arming patterns
from multirace/execatomic/blockmulti. It explicitly sets and verifies atomic mode and proves
actual shard owners. A parked EXEC retains the read cut. `ATOMIC-OFF-HOP-DELAY` exposes the mover
destination window; `ATOMIC-COMMIT-DELAY` exposes the blocking safe-watermark window. Blocked-client
registration and `atomic_commit_windows` witness the latter. Both tests demand zero stale cuts.
Only a missed window is retried, at most four times on fresh keys/connections; data failures are
terminal. LMPOP/ZMPOP have one selected owner in phase two, so OFF-HOP cannot park that phase;
their exact lost-write interleavings are covered by the serverless half of each gate row.

The two rows are `plain-write lost updates (atomic 0)` and `(atomic 1)` at `tests/gate.sh:1639`.
They run the production owner unit and then the corresponding live battery. `debug-*` now depends
on both release and production-unit builds. Their collection is at line **2814**, before the
quick-tier exit at line **2889**: quick 446 + 2 = **448**, full 463 + 2 = **465**.
The source inventory confirms 463 → 465, and the independently edited label fixture contains
exactly those 465 labels. Validated the fixture against proposed `EXPECT_FULL=465` in memory;
the on-disk constants were not changed. Until mainline updates them, the count/fixture guard is
expected to reject the mismatch.

Built artifacts (both server variants include the new diagnostic):

| Arm | Binary | SHA-256 |
|---|---|---|
| POST | `build/tomokv` | `9b4b875a1382f571fe401fa89448adb3857170257bd5697b5849cc6154ab8589` |
| PRE | `build/tomokv-atomfix-pre` | `4674397ed0f2b66d33be3147dab70e72317983466b2c6db2fcd3a5c6ddc9da53` |

`tools/atomfix_controls.py` copies source under `build/atomfix-pre/`, reverting exactly the five
cut expressions. A source comparison confirmed that only those five expressions differ. The
control retains the counter, uses the same other release objects, and includes both database
namespaces. It never edits production source. Reproduce the build and serverless proof:

```bash
cd /home/user/Projects/cx-atomfix
taskset -c 112-127 make -j16 all build/atomic-survivors-unit
taskset -c 112-127 python3 tools/atomfix_controls.py
taskset -c 112-127 make -j16 -f build/atomfix-controls.mk atomfix-controls
taskset -c 112-127 ./build/atomic-survivors-unit plain_0
taskset -c 112-127 ./build/atomic-survivors-unit plain_1
# Each following command must exit 1 at the corresponding assertion in the table above.
for case in plain_SMOVE_0 plain_LMOVE_0 plain_RPOPLPUSH_0 plain_LMPOP_0 plain_ZMPOP_0 \
            plain_MSET_0 plain_DEL_0 plain_UNLINK_0 plain_blocking_0 plain_blocking_1; do
    if taskset -c 112-127 ./build/atomic-plain-pre-unit "$case"; then
        echo 'FAIL: PRE unexpectedly passed'; exit 1
    else
        test "$?" = 1 || exit 1
    fi
done
```

**Mainline-only live commands — not executed by this lane.** Schedule the box first. The helper
uses a fresh empty persistence directory for each boot and kills only its own server PID.
Use free port 16399. Split geometry is exactly 16 shards, 6 io + 2 ex on eight CPUs; fused uses
eight CPUs and deliberately omits `--ratio`, which fused rejects.

```bash
cd /home/user/Projects/cx-atomfix
atomfix_live() (
    set -eu
    binary=$1; mode=$2; atomic=$3; shift 3
    port=16399
    test -z "$(ss -H -ltn "sport = :$port")" || exit 1
    data=$(mktemp -d "$PWD/build/atomfix-live.XXXXXX") || exit 1
    args=(--thread-mode "$mode")
    if [ "$mode" = 2s ]; then args+=(--ratio 6:2); fi
    taskset -c 0-7 "$binary" "${args[@]}" --shards 16 --atomic "$atomic" \
        --bind 127.0.0.1 --port "$port" --enable-debug-command yes \
        --key-lb 0 --client-lb 0 --flip-auto 0 --protected-mode no \
        --dir "$data" --save '' --appendonly no >"$data/server.log" 2>&1 &
    pid=$!
    trap 'kill -TERM "$pid" 2>/dev/null || true; wait "$pid" || true' EXIT
    ready=0
    for attempt in $(seq 150); do
        kill -0 "$pid" || exit 1
        if taskset -c 112-127 redis-cli -p "$port" PING 2>/dev/null | grep -q PONG; then
            ready=1; break
        fi
        sleep 0.2
    done
    test "$ready" = 1 || exit 1
    taskset -c 112-127 python3 tests/atomic_plain.py 127.0.0.1 "$port" --atomic "$atomic" "$@"
)

# POST: each must pass; covers both thread modes and both atomic settings.
for mode in 2s 1s; do
    for atomic in 0 1; do
        atomfix_live ./build/tomokv "$mode" "$atomic" || exit 1
    done
done

# PRE: isolated disposable data only. Require the named lost-data assertion, not just an exit.
if atomfix_live ./build/tomokv-atomfix-pre 2s 0 --case movers >build/atomfix-live-pre-AT1.log 2>&1; then
    echo 'FAIL: AT1 PRE unexpectedly passed'; exit 1
fi
grep -q 'AT1:.*preserves the acknowledged destination write' build/atomfix-live-pre-AT1.log || exit 1
for atomic in 0 1; do
    if atomfix_live ./build/tomokv-atomfix-pre 2s "$atomic" --case blocking \
        >"build/atomfix-live-pre-AT2-$atomic.log" 2>&1; then
        echo 'FAIL: AT2 PRE unexpectedly passed'; exit 1
    fi
    grep -q 'AT2:.*consumes the acknowledged wake push instead of re-parking' \
        "build/atomfix-live-pre-AT2-$atomic.log" || exit 1
done

# After the maintainer changes EXPECT_QUICK/FULL to 448/465:
# This includes multirace.py, execatomic.py and blockmulti.py in their existing batteries.
GATE_CORES=0-7 GATE_RATIO=6:2 tests/gate.sh iteration
```

Decision: POST must keep every acknowledged element (except the requested consumed element),
complete every waiter, and report zero stale cuts; each PRE control must fail at its named
assertion. Any missing arming witness is a failed test. No live PASS, gate result, or throughput
measurement is claimed in this handoff.

`git diff e279aeb4cf08ae2c39f26be679388b872fed4667 --stat`:

```text
 MEASURE-REQUEST-atomfix.md                    | 233 ++++++++++++++++++++++++
 Makefile                                      |   2 +-
 src/cmd/atomics_glue.inc                      |  10 +
 src/cmd/blocking.inc                          |   2 +-
 src/cmd/scatter_engine.inc                    |   8 +-
 src/cmd/t_server.cc                           |   5 +
 src/cmd/xshard.h                              |   1 +
 tests/atomic_plain.py                         | 252 ++++++++++++++++++++++++++
 tests/atomic_plain_checks.inc                 | 179 ++++++++++++++++++
 tests/atomic_survivors_unit.cc                |   7 +-
 tests/fixtures/nullrefresh-ledger-labels.json |   8 +-
 tests/gate.sh                                 |  12 ++
 tools/atomfix_controls.py                     |  56 ++++++
 13 files changed, 766 insertions(+), 9 deletions(-)
```
