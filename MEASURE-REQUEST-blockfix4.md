# Blocking correctness release fixes

## blockfix4

Baseline: `7d2f8a2051961a1942735fb6dc9b507d778e09d1` (`origin/cpp` at lane creation).
Worktree/branch: `/home/user/Projects/cx-blockfix4`, `cx-blockfix4`. No push.
Correctness processes and builds are restricted to CPUs 32–47; TomoKV, oracle
and Tcl control boots use ports 20200–20299. Every server inherits `LC_ALL=C`. No performance benchmark or full
iteration is run by this lane.

### Mechanisms and witnesses

The witnesses are the owner's round4 scripts, vendored under
`tests/blockfix4_repro/`. Their observations are promoted to assertions by
`tests/blockfix4.py`, invoked by the gate's `blockfix4` job. A missing parked
waiter, missing MVCC window, absent stolen-element hit, unexecuted creator,
wrong value or wrong exact error fails the row. Each attempt uses fresh keys.
Redis 7.4.10 at `/home/user/Projects/redis/src/redis-server` runs the same scripts.

| Item | PRE witness (io_uring / epoll) | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| 1 SCRIPT-PUSH-NO-WAKE | 36 / 36 script pushes needed a rescue push; held-record cases also missed publication before hold release | Final receipt pending | Deferred native publication marks the shard dirty; script scope restores the previous deferral state and publishes after the last command, or after its outer plain view closes | No ordered ready-key walk |
| 2 SCRIPT-PUSH-WAKE-POINT | 24 / 24 script replies returned LLEN=0 | Final receipt pending | One publication scope covers the complete EVAL/EVALSHA/FCALL activation, including error exits | EXEC-SEES-UNSERVED-STATE remains outside this lane |
| 3 BLOCK-MOVE-RESUME-NIL | 720 / 720 stolen-source hits returned nil | Final receipt pending | Reuse the existing blocking remap/registration path, preserving the original deadline and ROB/barrier; only a real timeout completes with null | No D11 serve-order change |
| 4 creator readiness | 256 / 256 missed wakes in 480 / 480 creator/control hits | Final receipt pending | Store image installation signals collection readiness; native pushes retain their existing waiter gate; remove mutation command allowlists; include owner-built GEO STORE | RESTORE-stream is NOT RUN pending the separate D9 format fix, as stated in the owner report |
| 5 removed stream | 126 / 63 foreign-stream data replies in 400 / 400 hits | Final receipt pending | Logical external-stream retirement releases old group waiters synchronously, before a later batch command can supply replacement stream data; replacement type chooses WRONGTYPE versus NOGROUP | Script/EXEC deferral and direct stream-to-stream replacement retain Redis's final-state behavior |
| 6 AT4.20-A0 | 2,195 / 4,154 null replies with a nonempty fallback, in 51,200 / 51,200 pops | Final receipt pending | A missed selected pop reuses the existing re-probe in either atomic mode; no retry-count-to-null shortcut; refresh an atomic-off retry's read cut | Queue admission may still return its existing explicit error |

The first PRE gate run failed all five added rows before production changes.
PRE evidence: `docs/blockfix4/pre-uring-witnesses.tar.gz`,
`pre-epoll-witnesses.tar.gz`, and their ledgers. The earlier POST functional
candidate passed all five rows on both engines: 108 script attempts, 720 stolen
move hits, 480 creator hits, 400 stream-removal hits and 51,200 pops per engine.
These are intermediate receipts; the final binary's receipts are recorded below.

The final io_uring witness job passed 116/116 legs, including its oracle legs.
With the complete removal inventory, TomoKV completed 108 ordinary/held script
pushes and 1,024 natural-MVCC script attempts (1,001 observed MVCC windows), all
with LLEN=1 and no rescue push; 720/720 stolen-source move windows re-parked
and consumed the second push; 480 creator wakes returned the oracle's values;
640 removed-stream hits gave the exact errors (160 WRONGTYPE, 480 NOGROUP);
all 51,200 MPOPs were non-null. The removal inventory adds ASYNC FLUSHDB,
ASYNC FLUSHALL and MSET replacement to the original five cases.
`docs/blockfix4/extended-proof-summary.json` derives these counts from
`post-extended-uring`. The earlier final-binary run, before adding MSET, is
retained in `post-uring-summary.json` (560 removal hits, 1,019 MVCC windows).
The complete job also passed with `--databases 16`, exercising the normal
namespace in addition to the default DB0 specialization.

The expanded PRE gate run, including natural-MVCC witnesses, failed all five
aggregate rows again.
Its eight no-hook legs produced 559 MVCC hits in 670 fresh attempts, including
34 hit failures and seven other wake failures. In particular, read-local 0
in 2s reproduced one lost wake in 103 observed MVCC windows. Failing PRE legs stop
early after ten defects; POST must complete all 128 attempts per leg and open
at least one MVCC window in each leg.

`ATOMIC-COMMIT-HOLD` also holds a resumed atomic BLMOVE. Its check requires the
move to finish immediately after releasing that hold, without a rescue push;
BLPOP/BRPOP must finish while the hold remains set. This distinction applies
equally to PRE and POST. The additional natural-MVCC runs use no DEBUG hold.

### Validation

The broad io_uring gate proof passed 334/334 rows; the additional fused debug
jobs passed 33/33, and fused blocking/atomic/notification jobs passed 19/19
on each engine. Remaining epoll and PAD-A receipts are pending.
The production-unit proof passed 30/30 rows. `make all` and all 51 targets in the first
`job_production_units` make command built; its two MDBQSBR control servers,
blockfix cost target and both blockfix2 unit targets also built. All five
freshness commands return zero (`docs/blockfix4/freshness.json`), including
`make -q all` and the complete target inventory.
The complete requested job list is `docs/blockfix4/required-jobs.txt`.
`tools/blockfix4_proof.py` runs those jobs through `tests/gate.sh`'s partial-job
interface, pins the oracle and both engines, archives every red and green
ledger, and refuses a binary change during a run. No EXPECT tally, ABBA or
iteration receipt is claimed by a partial proof.
An initial attempt to select `production_units` alone was rejected by the
gate because it is a build-only prerequisite; the successful run selected
its consuming jobs. That rejected invocation is retained too.

The existing Tcl manifest already requires the relevant removed/renamed-stream
assertions. Its remaining list skips describe D11 ordering, statistics,
replication or quicklist behavior; its script-blocking skips concern blocking
commands *inside* Lua. None is silently promoted on the strength of these fixes.
`tests/redis_tcl.py` now forwards the requested gate network engine to its
server boots; otherwise an epoll Tcl job would still test io_uring.

The initial `tests/gates_test.py` run had scheduler fixture timeouts while
compilation and GDB tracing shared the lane. Its raw failure log is retained;
a later rerun passed all 83 tests in 159.888 seconds after compilation and
tracing finished. Those first harness runs used its default ephemeral
socket-only fixtures. The final run pins those fixtures with
`GATE_TEST_PORT=20270` and passed all 83 tests in 145.694 seconds
(`docs/blockfix4/gates-test-bounded.log`). No timeout or assertion was relaxed.
`tests/redis_tcl_test.py` also passed its 10 tests.

The complete final io_uring Tcl rerun passed both modes: 39 manifest files and
1,875 passing assertions per mode (`gate-receipts/tcl-uring-repeat.json`).
The first run timed out in Lua's script-loading GC test while compilation and
tracing were active, and also hit the pub/sub unsubscribe assertion in 1s.
A focused PRE control reproduced that exact pub/sub assertion in 2s;
its scripting tests passed. This pre-existing pub/sub failure is reported and
left outside this blocking lane. All initial red results and the unchanged
successful full Tcl rerun are retained; no manifest skip or timeout changed.

The final io_uring differential job passed all 930 base comparison legs:
47 suites × five seeds × atomic 0/1 in split mode, and 46 suites × five seeds
× atomic 0/1 in armed fused mode (SORT has its existing split-only geometry).
Seeds were 7, 19, 20, 23 and 24. The suite also runs four fixed repetitions of
MULTI/atomic=1/seed=19 in each mode: all eight passed, for 938 comparisons.
These are the suite's existing sentinel repetitions, not retries of failures.
Both fused read-local activity checks and the complete mode-equivalence part
passed. The combined functional run retains
its two earlier Tcl failures; the separate complete Tcl rerun supplies the
passing Tcl result. Its first archive collector found concurrent run folders;
the recovered receipt names only the gate's own banner directory and records
that collection error.

### Cost and arms

`tools/blockfix4_scope.py` counts bounded, serverless execution in linked
production objects. It excludes fixture glue and non-Tomo library callees,
pins clock responses, and checks exact replies after every scope. The fixture
binds the actual owner context. GET/SET/INCR/MGET/MSET and LPUSH/RPUSH without
waiters cover batches 1 and 32, 1s/2s and both namespaces; MSET covers both
atomic settings. Separate local/cross-owner script and EXEC scopes quantify
their cost. These counts do not establish IPC or a throughput result.

**Zero added instructions: 64/64 ordinary-command pairs.** Every POST count is
less than or equal to PRE. Exact totals, scopes and exclusions are in
`docs/blockfix4/instruction-summary.md`; all raw count receipts, including
rejected compiler trials, are in `instruction-receipts.tar.gz`. The metadata
binds the fixture and linked server hashes. These scopes use read-local 0;
the live correctness matrix covers read-local 0 and 1.

The cold retirement helper and two existing helper inlining decisions keep
new blocking work off ordinary paths. The DB0 xshard compiler budget changes
from 159264 to 163360, the smallest tested value that passes the complete
ordinary-command scope matrix. This is a compile-time inlining budget, with
no runtime setting or behavior change.

| Added counted instructions | Normal 1s | Normal 2s | DB0 1s | DB0 2s |
|---|---:|---:|---:|---:|
| Local EVAL, per invocation (batch 1 or 32) | +27 | +123 | +28 | +124 |
| Cross-owner EVAL, one activation | +52 | +148 | +16 | +116 |
| EXEC, one INCR child | -16 | +14 | -60 | -62 |
| EXEC, 32 same-key INCR children | -140 | +820 | -824 | -826 |
| EXEC, 32 INCR children over eight shards | -203 | +757 | -1139 | -1141 |

EXEC totals match at atomic 0 and 1. The complete 44 script/EXEC PRE/POST pairs
are retained; these costs are not represented as zero.

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/blockfix4/pre-source/build/tomokv` | `d85693be2ed803887154381b1ebd67a2106347cb3171ce25160b38899c0ff6d6` |
| POST | `build/tomokv` | `cb7a70bbcf669f8657697a3708c9dd583dbf74fd0463da4ba590a1b8caf63a65` |
| PAD-A | `build/blockfix4/pad-a/tomokv` | `89a4dcb3d435b9bd033fb09d39f789f3a94c8fe0368d53b0ad2c14b446644438` |

PRE `.text` is 8,850,599 bytes; POST and PAD-A are 8,867,671 bytes (+17,072).
`.bss`, `.data` and `.tbss` sizes are unchanged. Full section and build details
are in `docs/blockfix4/binary-manifest.json`.

PAD-A is **(A) behaviour twin**: PRE behavior with POST's private blocking
registry layout and total `.text` size. It preserves PRE mechanisms, including
the failing witnesses. `tools/blockfix4_pad.py` produces it and the manifest.
It controls total text size and registry layout; it does not claim identical
function addresses or alignment. All eight public layout locks remain fixed.

### Maintainer measurements

Please run PRE, POST and PAD-A with the gate's own instrument on the quiet box.
Use the 14 generic cells (`docs/compat2/merit-cells.txt`): h05, h06, p8g, p8s,
d1g_l0, d1s_l0, m8g_l0, v1g_l0, d128g_l0, d32g_l1, d8s_l1, d32s_l1,
x9_32_l1 and x9_32_l0. Add 2s ratio 6:2 GET and SET at p1 and p32,
16 shards, eight server CPUs, retaining each cell's normal payload, connection
count and offered load. Record cycles/op, instructions/op and IPC for every arm.
Rate at matched offered load, or the cell's declared latency score, decides
regression; compare PAD-A against PRE to identify layout effects. This lane
makes no throughput claim.

### Gate arithmetic and exclusions

DQ = +5, DF = +5. `collect_job blockfix4` is before the quick-tier exit, and
the job emits exactly five rows: collection line 6293 precedes the quick-tier
branch at line 6479 (exit at 6483). `EXPECT_QUICK=999` and `EXPECT_FULL=1016`
are untouched. With only this lane's row change, the maintainer's new values
would be 1004 and 1021.

D11's ordered serve walk, EXEC-SEES-UNSERVED-STATE, sweep notification/slowlog
order, and tracking fixes are not implemented. The maintainer's performance
cells and full iteration are NOT RUN here under the task's runtime restriction.
The atomic RYOW battery's rate assertions are also NOT RUN under that restriction
(`GATE_PROOF_NO_RATES=1`); its correctness assertions remain enabled.
