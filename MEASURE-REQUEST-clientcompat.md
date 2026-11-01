## clientcompat

Implemented on `cx-clientcompat`, PRE `7d2f8a205`, production source through
`fbbd5ddd76`. No push. All commands are restricted to CPUs 64–79; builds use
`-j16`; correctness boots use `LC_ALL=C`, ports 20400–20499, 16 shards and the
job's declared geometry. No performance benchmark, load generator, or full
iteration gate was run. Correctness receipts below are partial job receipts,
not a full gate claim.

### Sealed arms

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/clientcompat/PRE/tomokv` | `b0811d7f86321e7c2e98acad2bc7f7dd4d29c1123cfbd56114287990741cdc39` |
| POST | `build/clientcompat/POST/tomokv` | `eb9efefa59d3a5d0e1bf5b9bb73af4984f6cda0b11cb03681c777b16026ba884` |
| PAD-A | `build/clientcompat/PAD-A/tomokv` | `f8287e0627d8075a6557d2729f7ba9c0539e83cf8d658f61a6a5ef7c2f75981c` |

PAD is kind **A, behavior twin**: PRE compatibility behavior with POST's exact
ELF section sizes/addresses and symbol table. `tools/clientcompat_pad.py`
changes the two cold namespace selectors to false, changing four bytes total.
It restores PRE pause exceptions, delayed INFO count, queue-time tracking,
MULTI control refusals and immediate TRACKING ON acknowledgement. No ordinary
GET/SET/INCR/MGET/MSET path calls the selector. POST and PAD have 8,864,375 bytes
of `.text`; `docs/clientcompat/pad.json` proves their section/symbol equality.
This is not an inverse control. Debug-only reductions of unrelated unit
executables preserve all allocated sections; the three sealed arms are intact.

### PRE witnesses and oracle

Each `clientcompat-*` job declares one Redis 7.4.10 oracle leg and 32 candidate
legs: 1s/2s × uring/epoll × databases 1/16 × atomic 0/1 × read-local 0/1.
`tests/clientcompat.py` uses the four schedules from the owner's
`round4-read/repro-tracking/t2_multitrack.py`. It observes all three phases
(QUEUED, EXEC, subsequent write) before rejecting a tracking result.

| Item | Redis oracle | PRE failures / 32 | Evidence |
|---|---|---:|---|
| D13 pause | PASS | 32 | ALL incorrectly admits CLIENT ID |
| D14 INFO | PASS | 20 | completed CLIENT KILL still counted disconnected clients |
| D16 + TRACK-MULTI-READS-UNTRACKED | PASS | 32 | early QUEUED invalidation and missing post-EXEC invalidation |
| 68d-5 ACL/subscription MULTI | PASS | 32 | ACL refused at queue time |
| TRACKING-ENABLE-RACE | PASS | 18 | write after ON's +OK lacks invalidation during directed owner occupation |

The initial 200-round ordinary enable/write search did not reproduce the race.
The stronger bounded LPOS occupation schedule did. Each geometry has 200
ordinary rounds and at most 12 fresh occupation attempts; failures are never
converted to skips. The report records observed occupation and later delivery
controls. The ordered missing invalidation after +OK is the defect witness;
client timing alone is not claimed to prove a particular owner instruction.
Raw JSON, oracle assertions and SHA-256s are in
`docs/clientcompat/pre-witnesses/summary.json` and its compressed archives.

### Changes and boundaries

* **D13:** ALL postpones CLIENT, RESET and MONITOR. WRITE follows Redis's
  WRITE/MAY_REPLICATE classification, including PFCOUNT, PUBLISH/SPUBLISH,
  dynamic scripts and queued EXEC children. DENYOOM remains its separate
  memory admission rule. Container commands are classified by subcommand:
  XGROUP HELP is not a write; FUNCTION LOAD/FLUSH/RESTORE/DELETE are writes.
  The source audit compares 328 executable command/subcommand entries with
  `/home/user/Projects/redis/src/commands/*.json`; zero static mismatches.
  Six script forms require dynamic flags and are identified separately.
  `server.c` command flags and `networking.c` pauseActions/blockPostponeClient
  are the reference. See `docs/clientcompat/pause-audit/registry.json`.
* **D14:** a display-only connected count is retired idempotently at disconnect,
  including self CLIENT KILL. The existing ownership count and migration
  protocol remain responsible for lifetime/reclamation. The new operations
  occur only on connection creation/closing, not ordinary commands.
* **Tracking MULTI:** queuing creates no read membership. EXEC prepares read
  receipts, observes the executed version certificate, and retires committed
  receipts in child order. Aborted/retried attempts remove only their pending
  memberships. This covers OPTIN/OPTOUT/BCAST/NOLOOP/REDIRECT and CACHING both
  before and inside MULTI. Own writes invalidate earlier reads; later reads
  can re-enroll the same key. Directed GET;SET and GET;SET;GET cases verify
  both invalidation and re-enrollment, with and without NOLOOP. WATCH-selected
  reads forward their original observed handler. The ordinary notify wrapper
  has no added transaction hook.
* **68d-5:** ACL and subscription-family commands queue. ACL SETUSER changes to
  the caller are simulated during permission preparation and applied only
  after commit; later children receive Redis's EXEC-time NOPERM error when
  appropriate. IO subscription effects complete in order using the parent's
  ROB slot, including SUBSCRIBE;PUBLISH;UNSUBSCRIBE and RESP2/RESP3 framing.
  SSUBSCRIBE queues, then yields Redis's exact DENY BLOCKING child error.
* **Enable race:** TRACKING ON waits for existing owner configuration mailboxes
  to acknowledge the notification configuration before replying +OK. The
  acknowledgement occupies padding in the 960-byte mailbox; no Server array
  or allocation was added. Only configuration-changing passes publish it.
  Refresh remains allowed during IO drain, preventing ON/FLIP/LB joins from
  deadlocking; ExDrain still freezes ownership updates. The 2s witness joins
  pending ON with FLIP and checks delivery after the move. Pending ON also
  wakes each remote owner once through its existing ring and polls its
  acknowledgement at a 1 ms idle interval. These operations are confined to
  the cold control wait; ordinary commands and empty timer lists add no work.

Deliberate deviations kept: **FLUSHALL/FLUSHDB inside MULTI remain refused**.
`xshard_prepare_flush` owns group placement, WATCH reservations, an independent
epoch, AOF grouping and phase-two collapse. `execute_flush` requires
`txn_group_ready`; `flush_after_decision` uses the FLUSH attempt's retry state.
EXEC children share their parent's decision and complete through
`xshard_multi_child_complete`. Admitting the existing design-A unit would not
compose these lifetimes or order later transaction reads/writes; child-aware
lowering is an algorithm change, outside the owner's conditional approval.
**DEBUG RELOAD/LOADAOF inside MULTI remain refused**, pending design B.

The tracking witness starts tracking before MULTI. Dynamic TRACKING ON/OFF or
mode changes among EXEC children are not covered by these new receipts; no
claim of exhaustive coverage of that separate combination is made. The ACL
ordering witness covers caller SETUSER changes and WATCH abort, not ACL-file
reloads interleaved with data children. These are explicit validation bounds.

### Instruction census

`tools/clientcompat_counts.py` runs finite serverless scopes, with PRE and POST
production objects and identical markers. The main product is 160 rows:
GET/SET/INCR/MGET/MSET × tracking off/on × batch 1/32 × 1s/2s × normal/db0
namespace × atomic 0/1. Tracking-on scopes include registration and retirement.
**52 equal, 108 lower, zero higher.** Thus none of the requested ordinary
command scopes executes added instructions in this census.

The count domain includes all executed functions in the linked executable,
including outlined STL, and excludes fixture bodies and shared libraries.
The earlier namespace-only count omitted outlined STL but counted inlined STL;
that asymmetry is why it was replaced. Original counts and rejected compiler
trials remain archived. These are instruction counts, not total end-to-end
cost, cycles, IPC, or throughput measurements.

Representative normal-namespace 2s, atomic 1, batch 1:

| Command | PRE off | POST off | PRE tracking | POST tracking |
|---|---:|---:|---:|---:|
| GET | 1556 | 1556 | 3663 | 3640 |
| SET | 1680 | 1680 | 2634 | 2618 |
| INCR | 2131 | 2131 | 3384 | 3368 |
| MGET | 10220 | 10193 | 22992 | 22875 |
| MSET | 16690 | 16679 | 22721 | 22721 |

`docs/clientcompat/command-totals.csv` contains every arm/cell, and
`command-sites.csv` attributes all 840 changed symbol rows. The ordinary read
handler is unchanged. Registry PreserveCaching metadata replaces a repeated
CLIENT name comparison; writes consume CACHING and return before the irrelevant
BCAST lookup. Cold EXEC code is isolated in clientcompat.cc. The Makefile pins
measured xshard compiler budgets per namespace to prevent unrelated inline
threshold drift; trial recipes and counts are retained under `budgets/`.

A separate 128-row census exercises real MULTI parsing/dispatch/retirement:
two GET or INCR children, one or several shards, tracking off/on, 1s/2s,
normal/db0, atomic 0/1, batches 1/4 transactions. All EXEC scopes add work:
**+214 to +1216.25 instructions per transaction**. Preparation adds ACL shadow
checks and receipt selection; tracked execution records version observations;
retirement applies committed IO effects, replays own writes in child order,
and promotes or cancels receipts. `session-totals.csv` gives every delta and
`session-sites.csv` attributes all 5104 changed symbol rows, including compiler
redistribution among outlined helpers. This cost is explicitly on MULTI/EXEC
and tracking control paths. `instruction-summary.json` ties both products to
the sealed server SHA-256s; retained build recipes reproduce the probes.

### Correctness validation

The first split/armed feature runs rejected two legacy test expectations:
CLIENT UNPAUSE bypassing PAUSE ALL, and refusing SSUBSCRIBE at MULTI queue time.
`climon2.py` now independently proves WRITE unpause and ALL postponement;
`pubsub.py` checks QUEUED followed by the exact DENY BLOCKING EXEC error and
absence of a subscription. Their complete replacement jobs pass **34/34 split
and 35/35 armed-fused rows**. The original four failures remain in the broad
ledger; `validation/feature-expectations-corrected.json` supplies the replacement
receipts. AT15's legacy refusal control is also replaced by admission checks
and its exact wire assertion is reused by the oracle-judged multi-controls row.
The additional atomic-unit and all AT4.12 jobs are listed in
`supplement-jobs.txt`; these add no public gate rows. Production bytes did not
change for these assertion updates.

Final execution is in progress. The tracking FLUSH-order run exposed idle
acknowledgement waits; the corrected POST/PAD-A arms above are built and their
complete 160/128-row instruction products retain exactly the reported counts.
Correctness validation is being repeated. Earlier receipts remain archived.
This section will be replaced with completed
receipts before delivery. The sealed POST passed **160/160** candidate legs across all five new
witnesses; every oracle leg passed. PAD-A failed all five gate rows as intended:
pause 32/32, disconnect 26/32, multi-tracking 32/32, multi-controls 32/32 and
enable-race 19/32 failing candidate legs. `docs/clientcompat/witnesses/summary.json`
and its compressed raw assertions retain both halves of this control. The sealed broad selection is
`docs/clientcompat/final-regression-jobs.txt`; its 120 selected jobs and required
prerequisites include the complete requested command families, Tcl both modes,
all feature-matrix geometries and multidb/FLIP/LB/transaction ordering jobs.
Standard differential seeds completed on io_uring: 235/239 split legs,
230/234 armed-fused legs (atomic 0/1), plus all 16 equivalence cells; zero
differences and all completion artifacts present. The same complete matrix also passed on epoll; see
`validation/differential-epoll.json`.
The AT15-expanded multi-controls witness also passed all 32 candidate legs and
the Redis oracle. See `validation/differential-uring.json`.
The sealed PAD-A negative controls are complete.
`coverage-extra-jobs.txt` adds the existing tracking-off EXEC, delivery-mask,
core notification, netcmd notification, MULTI/debug, blocking MULTI, snapshot
EXEC and INFO-input jobs found during the final coverage audit.

`make all`, all 51 explicitly enumerated production-unit targets, live MDBQSBR
arms and blockfix control/unit targets built successfully. See
`production-builds.json`, `production-targets.json` and `freshness.json`.
`python3 tests/gates_test.py`: **83/83 PASS** in the fully isolated CPU
allocation (147.185 seconds). Two earlier runs each had the same one-slot
scheduler 45-second deadline failure during concurrent correctness traffic;
the unchanged test passed after pausing both gate queues between jobs. The
PRE self-test also showed this deadline failure. All logs are retained under
`docs/clientcompat/validation/`; no timeout was widened.
The draft full Tcl run passed 2s; 1s failed a no-acknowledgement unsubscribe
assertion and timed out in the 50,000-script GC test during compilation. A
bounded PRE control reproduced unsubscribe/PUNSUBSCRIBE races in 6 of 20
mode/trial legs, including the exact failed assertion. Upstream util.tcl
consumes zero replies for the no-argument helper before another client
publishes. `pre-pubsub-control.json` retains every trial. No assertion or
timeout was weakened; the sealed full Tcl jobs both **PASS**, covering all 37 manifest files
(39 declared runs per mode). All six mode/promotion events are independently
checked in `validation/tcl-promotions.json`.

Tcl promotions: old ALL-pause precedence; CLIENT KILL SKIPME's immediate INFO
count; unsubscribe-inside-MULTI/publish-self. The transaction response-order
tracking assertion was already passing. `tcl-inventory.json` records named
known failures/skips in pause, tracking, introspection, info-command and multi.
Tracking #11715 also depends on tracking-table eviction/cron and stays skipped;
FLUSHDB-in-MULTI stays skipped for the design reason above.

Five new `clientcompat-*` rows are collected before the quick-tier exit:
**DQ=+5, DF=+5**, so maintainer constants should change **999/1016 → 1004/1021**.
`EXPECT_QUICK` and `EXPECT_FULL` were not edited. Tcl promotions add no row.

**NOT RUN:** full `tests/gate.sh iteration`, ABBA/performance tiers,
`flip_saturated`, the inline tailgen workload, and release-only stream/xmove
rate/size-ratio assertions omitted by `GATE_PROOF_NO_RATES=1`. Those start performance
benchmarks/load generators reserved to the maintainer by this task. They are
not included in the partial correctness verdict.

### Maintainer measurement request

Use the gate's own instrument on a quiet box, tracking **off**, with PRE, POST
and **PAD-A (behavior twin)**. `docs/clientcompat/measure-cells.txt` lists the
14 generic cells plus 2s GET/SET p1/p32 null cells, with all settings. Begin
with a PRE/PRE null and retain all legs, matched offered loads and per-cell
cycles/op, instructions/op and IPC. Use the gate's normal ABBA ordering.

The deciding number is rate at matched offered load (and the declared p1
latency score), with zero main-command regression. POST must hold against PRE;
PAD-A separates compatibility behavior from identical POST layout. With
tracking off and no compatibility operation in these cells, POST/PAD-A should
be a null. Instruction reductions alone do not establish a win. No throughput
claim is made in this lane. Append the results as MEASURE-RESULT.

Superseded arms/probes were deleted after retaining SHA-256s and counts.
`retired-artifacts.json`, `retired-probes.json`, `history/archives.json` and
`unit-debug-trim.json` record cleanup; debug trimming preserves allocated
section bytes, addresses and sizes. The three delivered arm files are kept.
