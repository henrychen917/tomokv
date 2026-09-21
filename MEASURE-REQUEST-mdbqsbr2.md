# mdbqsbr2 — parked-worker progress and shutdown

Launch reference: `0dfac1b7c` on `cx-mdbqsbr`. Mainline performance reference:
`b8fe404e2`. This lane does not run servers, the gate, or benchmarks.

## Evidence read before code changes

`build/gate-run.qIAHOf/jobs/multidb-1s-0-0/multidb.log` records two
swappers `[128, 128]`, 87 read batches and `multidb PASS`. On that same boot,
`multidb-serial.log` breaks the client barrier at line 116 and `output.log`
records a 30-second shutdown timeout for PID 2598272. The 1s/0/1 boot similarly
passes 256 busy swaps (51 batches), then times out at serial order and shutdown
(PID 2629815). All eight serial-order rows fail. Five of the eight preceding
multidb rows pass; the others fail, including a blocked-waiter SWAPDB in 2s/0/1.

All ten recorded timeout PIDs no longer exist in `/proc` (the eight multidb
boots, plus `rlcache` and `asan_batteries`); the inventory is retained in
`build/mdbqsbr2-evidence/historical-pids.json`. The `gate-srv-*` artifacts
are ordinary stdout logs, not directories or core dumps. They identify t0–t7
and their CPU placement, but contain no stacks, map tickets or drain-ack values.
**An exact historical non-acknowledging participant cannot be recovered from
these artifacts.** No live server was started to manufacture that evidence.

The other two hung jobs do not request `--databases 16` in the gate. In
particular, rlcache completed its churn and then its post-run PING timed out.
These failures are not attributed to map grace by this report; they reinforce
why full mainline gating, not only the new targeted rows, remains necessary.

## Diagnosis audit (before implementation)

The missing *retirement* wake is verified: `DatabaseMap::publish` only stores
the map, request and pending bit. The acknowledgement runs at the next outer
`DatabaseWorkScope` entry. IO, reordered IO and EX keep that scope across their
idle network wait. Thus an idle physical worker, including physical t0 (the
only reaper), depends on a natural wait return to acknowledge/reap.

However, the supplied causal explanation is not established by this tree:
`reclaim` uses `try_to_lock` and returns without sufficient acknowledgements;
neither publication nor SWAPDB waits for map grace. The map destructor is
already defaulted and contains no final grace wait. `Ring::submit_and_wait`
already passes a 50 ms timeout to liburing. The SWAPDB **namespace drain** does
wait asynchronously for IO/EX acknowledgements and has no deadline; its initial
wake is conditional on a parked snapshot and later wakes use queued MSG_RING.
The new coarse scope also extends the existing Client lifetime epochs through
IO waits. These are separate mechanisms; a missing map ack must not be reported
as a verified explanation of the live SWAPDB/shutdown deadlock.

The implementation makes retirement and namespace-boundary wakes explicit,
diagnoses both kinds of overdue participant independently, and moves shutdown
progress supervision to the existing main thread. It retains every map when
workers stop, then lets destruction after joins supply the final grace.

Live PASS claims and the exact historical blocked participant remain unavailable
until mainline runs the supplied real-boot proof and serial-order battery.

## Candidate design

Each configured multi-DB physical participant owns one nonblocking eventfd in
the cold map state, allocated before workers start. DB0 creates none. Both
preprovisioned IO/EX rings watch that physical fd with one-shot POLLIN requests;
the active ring drains/rearms its own request. A dormant ring's stale completion
is harmless on its next tenure. Epoll IO registers the same fd and epoll EX
includes it in its existing poll wait. There is no new thread or runtime knob.

After releasing the pointer and retire ticket, publication writes **every** fd,
unconditionally with respect to parked/role snapshots, including the publisher's.
No producer uses a foreign SINGLE_ISSUER SQ or depends on a future submit to send
this wake. The existing outer-scope acknowledgement remains the only proof that
the old pointer is no longer in use. Waking is not acknowledging, and a sampled
even, parked, stopped or role-changing participant is not silently waived.
SWAPDB's initial namespace fence, both stage transitions and fence release use
the same doorbells. An idle role gap acknowledges from its owning physical
thread. The existing dispatch, journal-before-publish, namespace drain, WATCH,
blocking and transaction barriers remain intact.

The map reader still performs one acquire pointer load. No per-operation wake,
registration, retry, RMW, allocation or reader wait was introduced. Eventfd
writes, clocks and broadcasts belong to cold publication/control paths. The
already-existing main thread supervises progress while it would otherwise be
blocked in joins. Worker t0 still performs ordinary asynchronous reclamation;
main can also reap and diagnose a stuck t0 using the same try-lock protocol.

`Ring::kWaitTimeoutMs` names the existing 50 ms tick. For N workers, a grace
budget is `2 * (N + 1) * tick`: two complete pass/wake opportunities per worker
plus main, pessimistically serialized. At the required N=8 this is 900 ms.
Namespace drain has three stages, so its total deadline is 2700 ms. Worker
shutdown uses that same 2700 ms budget from observing stop, plus at most one
50 ms supervisor sampling interval. The oldest pending ticket keeps its original
age; new swaps cannot extend an old debt indefinitely. Recovery publications are
aged from the start of live supervision, not time spent reading snapshot/AOF
files before workers exist. Every overdue diagnostic prints the mechanism,
elapsed/budget, namespace stage, request, and each physical participant's t-id,
OS tid, ack, exited, role, parked, stop, client epoch and IO/EX drain acks.
This is a fail-stop deadline, never a time-based permission to reclaim.

## Shutdown

A lifetime guard covers each complete physical-worker lambda in ordinary split,
split read-local, fused and reordered fused runtimes, including early boot exits
and final teardown. An ordinary role change does not execute that guard. Main
waits for exits with bounded condition-variable ticks before calling join; a
missing exit aborts loudly with the same participant inventory. The existing
sticky signal doorbell wakes ring waits on SIGTERM.

Once any worker stops/exits or the server stop flag is set, early map reclamation
is abandoned for the entire domain. No stopped worker is asked to acknowledge,
and no artificial ack frees a version that another worker may still hold.
Pending/live maps remain owned until DatabaseMap destruction after the joins.
The old default destructor already supplied that final grace; the new code
explicitly enforces the stop path and bounds worker shutdown instead of adding
a final acknowledgement barrier.

## Live proof for mainline (not run by this lane)

`tests/mdbqsbr_live.py` boots exactly eight cores, `--shards 16 --ratio 6:2
--databases 16`, in every mode/read-local/atomic cell. It verifies the live mode,
thread/shard counts and database count. Each arm/case gets fresh state and its
own directory, exact command, PID-owned process, server log and JSON receipt.

| Assertion | Witness | Negative control |
|---|---|---|
| Idle SWAPDB reply within 900 ms | At least four physical workers appear in kernel ring waits in two successive samples; then three actual swaps, creating two retirements | Matching long-park build with database wake writes removed must hit the SWAPDB socket timeout while the server is still alive |
| SWAPDB under load within 900 ms | A client completes SET/GET RYOW batches in DB2 before and across swaps of DB0/1; four other parked workers witnessed | Same missing-wake control with the load present; boot/arming/crash errors cannot count as the expected timeout |
| SWAPDB with BLPOP within 900 ms | `blocked_clients == 1` before the window; an infinite BLPOP follows its logical DB and receives the post-swap list value | Same missing-wake control while BLPOP is parked |
| Shutdown bounded for all three cases | Owned PID exits zero after SIGTERM within 2700 ms and emits the final shutdown report, including in the timed-out control | The broken arm is still required to terminate; any shutdown timeout fails the row and the harness kills/reaps only its owned PID |

The production arm uses its normal wait cadence. The second positive arm and
its negative twin both extend only the ordinary idle wait to
`2 * 3 * grace = 5400 ms`, longer than the reply deadline. Without this shared
schedule control, removing a wake alone can pass thanks to the existing 50 ms
tick: calling such a run a negative proof would be dishonest. The negative
additionally removes all database eventfd writes (retire and namespace stages),
not the sticky shutdown signal wake. It is a real boot with real io_uring waits;
no callback impersonates a participant or injects an acknowledgement. The
standalone eventfd unit separately isolates the *retirement-only* wake.

An unarmed kernel-wait window reboots on fresh state, at most eight attempts;
exhaustion fails. No tolerance grows and no case skips. A timeout anywhere
except the intended SWAPDB reply is a failure. The harness bounds child waits,
client sockets and load-thread joins, unwinds on SIGTERM/INT, and always reaps
its own child. The shutdown test deliberately keeps connections open until stop
to cover BLPOP/queued work: its definition of clean is zero exit plus the final
report, not a false assertion that no connections were open at SIGTERM.

Build the two test twins (builds only):

```sh
taskset -c 112-127 make -j16 mdbqsbr-live-arms
```

On the maintainer's scheduled eight-core allocation, run each combination:

```sh
python3 tests/mdbqsbr_live.py --binary build/tomokv \
  --parked-binary build/mdbqsbr2-park/tomokv \
  --no-wake-binary build/mdbqsbr2-no-wake/tomokv \
  --mode 1s --read-local 0 --atomic 0 --cores 0-7 --port 7900 \
  --output build/mdbqsbr2-live/1s-0-0
```

Repeat for `mode={1s,2s}`, `read-local={0,1}`, `atomic={0,1}`; each invocation
runs idle first, then load and BLPOP, with production/parked/no-wake arms.
Expected total: 24 production cases, 24 long-park positives and 24 timed-out
negative controls, each with a bounded shutdown. Then run the unchanged
`tests/multidb_serial.py` and existing multidb battery on each normal production
boot, and mainline's full `tests/gate.sh iteration`.

The gate builds the twins in `production_units`; each existing multidb row now
runs this proof before its original busy battery, followed by its existing
serial-order row on the original boot. **No ledger row was added or retired.**
The collection remains above the quick exit: `EXPECT_QUICK=438`,
`EXPECT_FULL=454` remain unchanged. Failure-only shutdown rows are never added
to these expectations. The long-park twins are scheduling/negative controls,
not performance padding; they must never substitute for a measurement PAD.

## Layout and padding control

All locked hot sizes and the audited Server member offsets remain unchanged.
`DatabaseMap` is still 120 bytes; participant slots are still 64 bytes. Cold
`DatabaseMap::State` grows 56→192 bytes and retired entries grow 16→24 bytes.
The additional fd per physical worker is included in the open-file reservation.

For that cold-layout/text change, `build/tomokv-mdbqsbr2-pad` is **PAD kind A
(behaviour twin)**: launch PRE behaviour from `0dfac1b7c`, with 136 bytes of
unused State tail and eight unused bytes per retired entry to match POST's cold
sizes, then unreachable padding to match POST's aggregate `.text` size. It
also gives Participant an empty nontrivial destructor to preserve POST's array
allocation cookie (one extra 64-byte alignment unit), without any wake/fd work.
It retains the rejected PRE progress behaviour and is not a correctness candidate.
Its isolated source is `build/mdbqsbr2-pad-source`; the base link and padding
receipt are under `build/mdbqsbr2-evidence`. PRE is also preserved byte-for-byte
as `build/tomokv-mdbqsbr2-pre` before rebuilding POST.

This matches cold allocation sizes and total text size, **not every function's
address or branch layout**. No kind B inverse control is supplied: POST's text
is larger, so adding padding cannot restore PRE's smaller size. There is no
performance win claim. Mainline should require the normal full headline ABBA
against the trusted reference, with cycles/op, instructions/op and IPC. If
attributing any change to this repair, compare PRE / POST / PAD(A) at the same
offered load in both modes, databases 1/16, GET/SET, p1/p32, on the same eight
cores and 16 shards (split ratio 6:2). POST must preserve the mainline rate
verdict; any movement also present in PAD is a placement confound. All rates and
counters are pending mainline, never inferred from the one-load disassembly.

## Local verification and artifacts

Builds and serverless tests use only cores 112–127; exact eight-core fixtures
use 112–119. The original 13 selections and their lifetime/UAF fault controls
remain. Additional selections check all eight eventfds, retained maps after
stop with a missing t1 acknowledgement, and a deterministic expired live-t1
deadline. The no-wake unit control must fail its readable-doorbell assertion;
the expired-ticket run must abort and print t1 with ack=0. A further negative
ignores stop and must abort instead of passing the shutdown retention check.
Local build/test and structural receipts are retained in
`build/mdbqsbr2-evidence/`.

Final local results:

| Check | Result |
|---|---|
| Release, ASAN/UBSAN, TSAN and both live proof twins | Built successfully; final `make -q` checks current |
| ASAN/UBSAN positive selections | 15/15; all original 13 retained |
| ASAN control driver | 20/20 invocations: the positive suite plus 19 expected failures, including missing wake, ignored stop and expired live ack |
| TSAN positive selections | 15/15, no runtime report (`setarch x86_64 -R`, `halt_on_error=1:exitcode=66`) |
| Serverless namespace boundary | Eight PASS witnesses, including both modes and read-local admission windows |
| Serial oracle self-test | Legal orders accepted; stale-stamp counterexample rejected |
| Disassembly / footprints | One acquire map-pointer load, no reader RMW/store; DB0 scope empty; all locked sizes and audited offsets unchanged; both structural negative controls reject |
| PAD(A) | Cold sizes verified by GDB; aggregate `.text` exactly matches POST |
| Python / shell syntax | PASS |
| Real boots, live serial-order, full gate, rates/counters | NOT RUN — mainline owns these |

The final release has 7,445,596 `.text` bytes; preserved PRE has 7,435,564
(+10,032). PAD(A) adds 9,520 unreachable bytes to its cold-size-matched PRE
construction. No instruction-count or performance parity claim follows from
that match. TSAN compilation retains the existing fence/optional-scope compiler
warnings; the runtime selections are clean.

A deterministic failure receipt names the participant, rather than hanging:

```text
fatal: database retire acknowledgement timeout elapsed_ms=901 grace_bound_ms=900 stage=0 request=1
  participant=t1 os_tid=0 ack=0 exited=0
```

Here OS tid 0 explicitly denotes the serverless fixture; a live worker records
its real OS tid at entry. This is not represented as the vanished historical
server's participant identity.

### Artifact hashes

These are files in this worktree, not assumed external reference hashes.

| Artifact | SHA-256 |
|---|---|
| `build/tomokv` | `de6da9fc51900afe76abd6d8d5cf68c2a964834ed897c86cd977793ef90731d6` |
| `build/tomokv-mdbqsbr2-pre` | `5adbd64cd40023783c0c0b3f2947f25bf1565b9aa64eb694730a0e08deba454f` |
| `build/tomokv-mdbqsbr2-post` | `de6da9fc51900afe76abd6d8d5cf68c2a964834ed897c86cd977793ef90731d6` |
| `build/tomokv-mdbqsbr2-pad (A)` | `3edb23b3352b5695f99afec7471e85806e69bde4989999d69c42ee38c5efdd16` |
| `build/mdbqsbr2-park/tomokv` | `40effcbc2364e570ac83a2cd3c7390b63b564611ba2e910f4d773fdbeea36f57` |
| `build/mdbqsbr2-no-wake/tomokv` | `141fc16799b1872118e7913e7d441e5c0b81330949ec350ddba9265c5b432ac3` |

`build/tomokv` is POST. The complete receipts, per-control stdout, compiler logs,
PAD source diff, construction metadata, ABI arrays and hashes are in
`build/mdbqsbr2-evidence/`. The implementation is committed on `cx-mdbqsbr`; no
push, server, gate, load generator or performance run was made by this lane.

The historical deadlock's exact blocker remains **unverified**, not silently
assigned to map grace. Mainline must run the new live matrix and the existing
serial-order/full-gate checks before this repair can be called a live fix. If a
participant still stalls, the new bounded diagnostics distinguish retirement,
namespace drain and worker shutdown and identify its physical and OS ids.

### Review diff

Repair-only reference: launch `0dfac1b7c`. Cumulative lane reference:
`b8fe404e2` (includes the pre-existing launch gate-reference metadata update).

<!-- final-diff-stat -->

`git diff 0dfac1b7c --stat`:

```text
 MEASURE-REQUEST-mdbqsbr2.md | 330 ++++++++++++++++++++++++++++++++++++++++++++
 Makefile                    |   8 ++
 src/cmd/multidb.cc          | 251 +++++++++++++++++++++++++++++++--
 src/cmd/multidb.h           |  35 ++++-
 src/core/ex_loop.h          |  12 +-
 src/core/genthread.cc       |   6 +-
 src/core/io_loop.h          |  24 +++-
 src/core/reorder.cc         |  14 +-
 src/core/rl2s.cc            |   8 +-
 src/core/server.h           |   5 +-
 src/main.cc                 |  18 ++-
 src/net/uring.h             |  16 ++-
 tests/gate.sh               |  17 ++-
 tests/mdbqsbr_checks.py     |  15 +-
 tests/mdbqsbr_live.py       | 301 ++++++++++++++++++++++++++++++++++++++++
 tests/mdbqsbr_unit.cc       |  37 +++++
 tools/mdbqsbr_artifacts.py  |  11 ++
 17 files changed, 1063 insertions(+), 45 deletions(-)
```

`git diff b8fe404e2 --stat`:

```text
 MEASURE-REQUEST              |  24 ++-
 MEASURE-REQUEST-mdbqsbr.md   | 502 +++++++++++++++++++++++++++++++++++++++++++
 MEASURE-REQUEST-mdbqsbr2.md  | 330 ++++++++++++++++++++++++++++
 Makefile                     |  38 +++-
 src/cmd/multidb.cc           | 438 ++++++++++++++++++++++++++++++++++---
 src/cmd/multidb.h            | 130 ++++++++++-
 src/core/ex_loop.h           |  19 +-
 src/core/genthread.cc        |   6 +-
 src/core/io_loop.h           |  31 ++-
 src/core/reorder.cc          |  21 +-
 src/core/rl2s.cc             |   8 +-
 src/core/server.h            |  39 +++-
 src/main.cc                  |  18 +-
 src/net/uring.h              |  16 +-
 tests/gate.sh                |  19 +-
 tests/gate_measurements.json |   8 +-
 tests/mdbqsbr_checks.py      |  56 +++++
 tests/mdbqsbr_live.py        | 301 ++++++++++++++++++++++++++
 tests/mdbqsbr_probe.cc       |  17 ++
 tests/mdbqsbr_unit.cc        | 443 ++++++++++++++++++++++++++++++++++++++
 tests/multidb_db0_unit.cc    |   7 +
 tests/multidb_unit.cc        |   4 +
 tools/mdbqsbr_artifacts.py   | 166 ++++++++++++++
 23 files changed, 2561 insertions(+), 80 deletions(-)
```

## mdbqsbr3

Launch reference: `1acfe491a` on `cx-mdbqsbr`. Harness fix commit: `70dbcac00`.
No server source, Makefile, gate row or expected row count changed.

Mainline's 2026-09-21 08:50 live run passed all four `2s` combinations of
read-local/atomic, including idle, load, BLPOP, all three arms and bounded
shutdown. All four `1s` combinations failed at boot before exercising those
checks: the harness always supplied `--ratio 6:2`, and the server rejected it
with `--ratio is unavailable with --thread-mode 1s: every thread handles
networking and execution`. These were harness boot failures, not SWAPDB results.

This section corrects the earlier claim that `--ratio 6:2` applies "in every
mode". `build_command()` now omits that pair only for `1s`; the entire `2s`
argv is unchanged. The audit of `src/core/config.h` found two fused-specific
validation rejections: a configured ratio and enabled `--flip-auto`. The latter
is absent from this harness and defaults to `0`. All remaining flags are valid
in both modes. This matches `tests/gate.sh`'s `boot_fused`, which omits the ratio
and selects the `fused` alias of `1s`.

Fixed argv per mode, for every production/parked/no-wake binary (`BIN`), port
(`PORT`), and read-local/atomic cell (`RL`, `AT` each 0 or 1). `CORES` is the
mainline's eight-core allocation, `0-7` in the reported run:

```sh
taskset -c "$CORES" "$BIN" --bind 127.0.0.1 --port "$PORT" --thread-mode 1s \
  --shards 16 --databases 16 --read-local "$RL" --atomic "$AT" \
  --enable-debug-command yes --save '' --protected-mode no

taskset -c "$CORES" "$BIN" --bind 127.0.0.1 --port "$PORT" --thread-mode 2s \
  --shards 16 --ratio 6:2 --databases 16 --read-local "$RL" --atomic "$AT" \
  --enable-debug-command yes --save '' --protected-mode no
```

The existing live checks still require eight fused workers in `1s`, or six IO
and two EX workers in `2s`, plus sixteen shards and sixteen databases. Each
launch still records its exact argv in `command.json`.

Launch/readiness/boot-verification exceptions now raise `BootFailure` containing
the original error, child PID/exit status when available, and the last 25 lines
of the combined stdout/stderr `server.log`. An empty/unreadable log is identified
explicitly. `result.json` records `failure_phase: boot` and the same diagnostic;
these errors cannot become the no-wake arm's expected SWAPDB timeout. Child
cleanup and the existing arming/SWAPDB/shutdown checks remain in place.

Serverless verification, all executed with `taskset -c 112-127`:

| Check | Result |
|---|---|
| `python3 tests/mdbqsbr_live_test.py -v` | 6/6 tests pass: all eight argv cells, exact split preservation, launch/argv receipt binding, negative control, and mocked boot exit/deadline/launch errors with log diagnostics and child cleanup |
| Frozen pre-fix argv negative control | All four fused argv cells fail the **same** `assertNotIn('--ratio', ...)` assertion; accepting any old argv would fail the unit |
| Actual launch-baseline cross-check | Evaluated only the original argv expression from `git show 1acfe491a:tests/mdbqsbr_live.py`; it exactly matches the frozen control in all eight cells, fails the fused assertion in all four, and matches the fixed split argv in all four |
| `make -j16 all mdbqsbr-live-arms` | Exit 0; production, parked and no-wake builds all current, with no recompilation required |
| `git diff --check` | PASS |

No server, gate, benchmark or load generator was run. The diagnostic units mock
both process creation and connections; even an unexpected call fails locally.
Receipts and the reproducible historical-expression check are retained under
`build/mdbqsbr3-evidence/`: `unit.log`, `historical_control.py`,
`historical-control.log`, and `build.log`.

Mainline reruns all eight mode/read-local/atomic combinations with fresh output
directories (72 case/arm runs: idle/load/BLPOP x production/parked/no-wake x 8),
then the full gate. Live validation of the repaired `1s` argv remains pending;
the serverless result is not a live PASS claim. No push was made.

`git diff 1acfe491a --stat`:

```text
 MEASURE-REQUEST-mdbqsbr2.md |  75 ++++++++++++++++++++++
 tests/mdbqsbr_live.py       |  49 ++++++++++++---
 tests/mdbqsbr_live_test.py  | 149 ++++++++++++++++++++++++++++++++++++++++++++
 3 files changed, 266 insertions(+), 7 deletions(-)
```

## mdbqsbr4 — reproduced reciprocal client-close epoch deadlock (2026-09-22)

Launch: `d034ac11f`, branch/worktree `cx-mdbqsbr`. Reproduced BEFORE changing
production code. All builds/tests stayed on CPUs 112–127; servers used exactly
112–119, and the original battery processes used 120–127. Builds used
`taskset -c 112-127 make -j16`. No full gate, benchmark, or push was run.
The evidence root below is `build/mdbqsbr4-evidence` in this worktree.

### Reproduction commands and artifacts

The PRE binaries were preserved from the failing tree before rebuilding:
`pre/tomokv`, `pre/tomokv-asan`, `pre/tomokv-rlcachedbg`. The latter two came
from the gate's own `build/gate-cache` binaries. `sha256.txt` identifies every
PRE/POST binary, including the serverless negative. Each boot used a fresh
persistence directory; exact server/client argv, PID, output, and exit status
are retained in `command.json`, `*-command.json`, `pid`, logs, and `result.json`.

These are the original commands, translated only to this lane's CPUs, private
ports and fresh directories. `MDB4=build/mdbqsbr4-evidence`; start/stop the owned
server around each block, not between batteries within a block:

```sh
# jobs/multidb-1s-0-1: 8 fused workers, no --ratio, 16 shards and databases.
taskset -c 112-119 "$MDB4/pre/tomokv" --port 17964 --bind 127.0.0.1 \
  --shards 16 --dir "$MDB4/pre-multidb/data" --thread-mode fused \
  --atomic 1 --read-local 0 --databases 16 --enable-debug-command yes \
  --appendonly yes --appendfsync no --save ''
taskset -c 120-127 python3 tests/multidb.py 127.0.0.1 17964 --read-local 0 --persistence
taskset -c 120-127 python3 tests/multidb_serial.py 127.0.0.1 17964 \
  --output "$MDB4/pre-multidb/serial.json"

# jobs/asan_batteries: exactly the same boot and battery order; default databases=1.
taskset -c 112-119 "$MDB4/pre/tomokv-asan" --port 17964 --bind 127.0.0.1 \
  --shards 16 --dir "$MDB4/pre-asan/data" --ratio 6:2 --atomic 1 --enable-debug-command yes
taskset -c 120-127 python3 tests/torture.py 127.0.0.1 17964
taskset -c 120-127 python3 tests/ryow.py 127.0.0.1 17964
taskset -c 120-127 python3 tests/atomic_torn.py 127.0.0.1 17964
taskset -c 120-127 python3 tests/atomic_ryow.py 127.0.0.1 17964 --no-rate-assertions

# jobs/rlcache explicitly overrides the launcher's 16 shards with 64; databases=1.
taskset -c 112-119 "$MDB4/pre/tomokv-rlcachedbg" --port 17966 --bind 127.0.0.1 \
  --shards 16 --dir "$MDB4/pre-rlcache/data" --thread-mode fused --shards 64 \
  --atomic 1 --read-local 1 --enable-debug-command yes
taskset -c 120-127 python3 tests/rlcache_churn.py 127.0.0.1 17966 25 48
```

Also reproduced rlcache with the requested **16 shards**, omitting the later
`--shards 64`: `pre-rlcache16/` and `post-rlcache16/`. Thus the finding does not
depend on that gate-specific override. The local PID-owning reproduction drivers
are `reproduce.py`, `post-reproduce.py`, and `rlcache16.py` in the evidence root.
They bound subprocess waits, disable core dumps, and kill/reap only their own
children. The server pre-exec hook permits the diagnostic sibling GDB under
this machine's `ptrace_scope=1`; it does not alter server behavior.

### All-thread stacks; waiter and missing waker

GDB ran on CPUs 120–127 with `-q -nx -batch -ex 'thread apply all bt 24' -p PID`.
`epochs.gdb` additionally records every stalled IO's physical id, all client
work epochs, its active set, and its captured client fences. Full stacks include
the supervisor and every worker, not just the currently selected thread:

| Reproduction | Stack/state files under evidence root | Observed waiter → missing progress |
|---|---|---|
| serial-order | `pre-multidb/multidb_serial-stacks.txt`, `pre-multidb/final-stacks.txt` | t5 / LWP 452442 is in `client_executor_quiesced`, loading t0's epoch; t0 / LWP 452437 is itself repeating `close_client` inside `flush_ready` |
| ASAN RYOW/torn | `pre-asan/ryow-stacks.txt`, `atomic_torn-stacks.txt`, `atomic_ryow-stacks.txt`, `epoch-cycle.txt`, `final-stacks.txt` | t2 / LWP 453818 holds 35081 and waits for t3's 24051; t3 / LWP 453819 holds 24051 and has captured t2's 35081 |
| armed rlcache | `pre-rlcache/rlcache_churn-stacks.txt`, `epoch-cycle.txt`, `final-stacks.txt` | t2 / LWP 458334 holds 749315 and waits for t5's 1025469; t5 / LWP 458337 has captured t2's 749315; all eight workers are in the close walk |
| 16-shard rlcache | `pre-rlcache16/rlcache_churn-stacks.txt`, `final-stacks.txt` | the same active-set close/epoch wait, without the 64-shard override |

The repeating stack is:

```text
IoLoop::run_loop                     owns DatabaseWorkScope / outer odd client epoch
  IoLoop::flush_ready                revisits the reinserted closing client
    IoLoop::close_client             removes it, then marks it active again
      IoLoop::client_executor_quiesced  waits for the captured foreign epoch to change
```

The missing waker is the foreign worker's **ClientWorkScope destructor release
store at its pass boundary**. It cannot execute while that worker spins inside
its own close walk. An eventfd wake cannot advance either stack. In the serial
reproduction every map participant had already acknowledged request 786; the
shutdown diagnostic shows stage=0 and ack=786 for all eight. ASAN/rlcache need
no SWAPDB at all. The map grace acknowledgement and namespace doorbells were
not the wait causing this cycle.

### Root cause and fix

The QSBR conversion extended `ClientWorkScope` over the entire IO pass. The
existing close path erases a releasable client from `active_`, calls
`close_client`, and leaves the cursor unchanged. `close_client` can then discover
an unfinished foreign client epoch and reinsert the same client. This repeats
inside the same pass. Two closing IOs can capture each other's outer epochs and
both prevent the release store the other needs. Before whole-pass IO scopes,
ordinary split IO did not create those mutual lifetime participants.

The fix checks `client_executor_quiesced` alongside the existing asynchronous
pub/sub fence **before erasing from the active walk**. A pending fence keeps the
client in place and advances the cursor; a later pass retries after the worker
has really ended its scope. The existing checks in `close_client` remain.
No lifetime fence is waived, no reader retries, and no epoch is synthesized.
This is a close-loop progress correction, not a QSBR design change.

Production changes are one close predicate in `src/core/io_loop.h` and its
generated counterpart in `src/core/reorder.cc`. `tests/r7shadow_sync.py` now also
preserves the pre-existing reordered-loop test-hook identity when regenerating.
There is no new per-operation work, reader counter, lock, knob, or layout field.
The map reader remains one acquire pointer load; the DB0 scope still disassembles
to `endbr64; ret`. `post-read.asm` and `post-db0-scope.asm` retain the disassembly.
Compiling `tests/mdbqsbr_probe.cc` in both variants passed all eight required
layout locks and the 120-byte DatabaseMap lock. This is a correctness fix;
no performance/PAD arm or performance claim is proposed.

### Regression and negative controls

The existing `core concurrency lifetime` selection now forces two IO scopes
with reciprocal captured epochs in the gate's eight-worker/16-shard fixture.
It asserts the window is armed, runs the actual close pass, verifies both
clients remain protected, releases one scope at a time, and verifies eventual
reclamation even while newer scopes are active. It covers split, fused and
reordered fused. The fused tail uses an in-memory empty CQ; no kernel ring,
listener or worker loop is started by this test.

The new test was first compiled against the unmodified PRE implementation and
saved as `pre/core-concurrency-unit`. This command fails at its internal
five-second watchdog with exit 1 and the following diagnostic; the outer timeout
is only a second containment boundary:

```sh
taskset -c 112-119 timeout --kill-after=1 10 \
  build/mdbqsbr4-evidence/pre/core-concurrency-unit close-cycle
# ARMED close-cycle mode=2s reorder=0: reciprocal IO epoch waits
# FAIL core concurrency: close pass did not return while peer epoch was held
```

`pre-close-cycle.log` records the failure. POST `build/core-concurrency-unit
lifetime` passes all three armed schedules under ASAN/UBSAN with leak detection;
see `post-lifetime.log`. A hang, early free, unarmed window or incomplete reclaim
fails the row; there is no skip/tolerance fallback.

The old live proof deliberately kept admin/load/BLPOP connections open until
SIGTERM, then closed them after server death. It tested namespace wakes and
shutdown without driving simultaneous ordinary client teardown. Its serverless
loop-coverage hook likewise returned before transport/close work. Both blind
spots are now covered: the lifetime selection drives the actual close walk, and
`tests/mdbqsbr_live.py` adds a production `disconnect` case running the gate's
unchanged barriered serial-order battery before shutdown. It requires all child
connections to drain back to the single admin, then PING, three bounded swaps,
and clean shutdown. The serial subprocess has a 21.6-second outer deadline;
its timeout or nonzero exit always fails, never counts as a no-wake success.

The extended live proof rejects the preserved PRE server too
(`pre-live-disconnect/`): serial traffic stalls and the server's existing
namespace watchdog aborts. All eight POST mode/read-local/atomic combinations
pass (`post-live-disconnect/`), including client drain and zero-exit shutdown.
The original parked/no-wake arms are unchanged and remain for mainline's rerun.
Ten serverless live-harness checks pass, including deadline, child failure and
undrained-client controls. The existing QSBR runner passes all 20 checks,
including its fault/deadline controls (`post-map-units.log`).

### Gate-shaped outcomes and remaining mainline work

| Same battery/boot sequence | PRE | POST |
|---|---|---|
| multidb then serial, 1s / rl0 / atomic1 / DB16 / AOF | multidb passes; serial hangs, BrokenBarrierError after 30.16 s | both pass, clean shutdown |
| ASAN torture | passes in this reproduction | passes |
| ASAN RYOW, after torture | hangs; socket timeout after 31.06 s | passes |
| ASAN atomic torn/window, same boot | times out on the already-stalled server | passes |
| ASAN atomic RYOW, same boot | times out on the already-stalled server | passes |
| rlcache, actual gate override: 64 shards / 48 workers / 25 s | churn finishes, post-run PING hangs | all five checks pass; 33 shard moves, local hits and cached blocks witnessed |
| rlcache, requested 16 shards / 48 workers / 25 s | same close-cycle hang; bounded failure | all five checks pass; 6 shard moves, local hits and cached blocks witnessed; clean shutdown |
| server termination after original reproductions | all three abort after the existing shutdown bound | all three exit 0 and emit final shutdown reports |

These are correctness observations, not rate comparisons. In particular,
torture itself did not hang in the PRE replay: RYOW subsequently opened the
cycle, and the following batteries inherited that stalled server, as they do
in the gate. POST ASAN logs contain no sanitizer error, and the read-local
logs contain no sink/cache/ring ownership violation.

The reported `ABBA comparison + saturation negative controls` failure has a
separate, verified test-harness cause: `LedgerWiring.test_multidb_rows_fail_independently`
did not stub `unit_ready`, the live proof or `CORES`, so its successful first row
was always FAIL. Reproduced its four failures serverlessly, then updated the
stub and added live-proof failure/skip and missing-build cases. All 14 matrix
cases pass. No measurement or full ABBA suite was run.

No gate row was added or retired, and `tests/gate.sh` was not edited.
The lifetime collection is line 2690, ABBA self-test line 2790, and the existing
multidb collection line 2796; all precede the quick exit at line 2819.
Expected counts remain **quick 438 / full 454**.

Builds: release and ASAN/UBSAN units via the root Makefile; instrumented server
variants via `build/mdbqsbr4-evidence/gate-build.mk`, using exactly the gate's
ASAN/read-local-debug flags and source list. Every build is pinned to 112–127
with `make -j16`. Final `make -q all build/core-concurrency-unit build/mdbqsbr-unit`
passes. The final release rebuild is byte-identical to the POST binary exercised
above (SHA-256 `22ba8f64d697a3d178a2944df9b8d5dceb6e9f3b60bc35e01d7087a73925d573`).

Mainline still owns the original full live-proof matrix, differential batteries
and full iteration gate. The differential matrix was not independently rerun,
and this report does not claim that all 19 original failing rows are now green.
Run the usual gate; its existing rows automatically include both new regressions.
No push was performed.

`git diff d034ac11f --stat` (including this report):

```text
 MEASURE-REQUEST-mdbqsbr2.md    | 217 +++++++++++++++++++++++++++++++++++++++++
 src/core/io_loop.h             |   9 +-
 src/core/reorder.cc            |   9 +-
 tests/core_concurrency_unit.cc |  98 ++++++++++++++++++-
 tests/gates_test.py            |  20 ++--
 tests/mdbqsbr_live.py          |  40 +++++++-
 tests/mdbqsbr_live_test.py     |  30 ++++++
 tests/r7shadow_sync.py         |   2 +
 8 files changed, 405 insertions(+), 20 deletions(-)
```
