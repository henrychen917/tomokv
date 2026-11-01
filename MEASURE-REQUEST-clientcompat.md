## clientcompat

Implemented on `cx-clientcompat`, PRE `7d2f8a205`, production source through
`694fae5c73`. No push. All commands are restricted to CPUs 64–79; builds use
`-j16`; correctness boots use `LC_ALL=C` and ports 20400–20499. Standard gate
geometry is 16 shards at 6:2; individual jobs retain their declared overrides.
No performance benchmark, load generator, or full
iteration gate was run. Correctness receipts below are partial job receipts,
not a full gate claim.

### Sealed arms

| Arm | Path | SHA-256 |
|---|---|---|
| PRE | `build/clientcompat/PRE/tomokv` | `b0811d7f86321e7c2e98acad2bc7f7dd4d29c1123cfbd56114287990741cdc39` |
| POST | `build/clientcompat/POST/tomokv` | `346d035c03e434604778e164172516cc5e1bfc8ee9fb248ded307f54dbb25d01` |
| PAD-A | `build/clientcompat/PAD-A/tomokv` | `54084673401c693fb9ba466ba9671bed153cc7f0fccc50fb2be2240085e3b874` |

PAD is kind **A, behavior twin**: PRE compatibility behavior with POST's exact
ELF section sizes/addresses and symbol table. `tools/clientcompat_pad.py`
changes the two cold namespace selectors to false, changing four bytes total.
It restores PRE pause exceptions, delayed INFO count, queue-time tracking,
MULTI control refusals and immediate TRACKING ON acknowledgement. No ordinary
GET/SET/INCR/MGET/MSET path calls the selector. POST and PAD have 8,884,599 bytes
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
  PING formatting also follows the subscription state at its own child:
  RESP2 switches to the pubsub `pong` array after SUBSCRIBE and back to an
  ordinary reply after the final UNSUBSCRIBE; RESP3 keeps ordinary PING replies.
  Keyspace/keyevent records for pending subscription children are retained even
  before the server has its first subscriber. The committed IO phase publishes
  each child's events before applying subsequent subscription changes, joining
  the existing notification chain acknowledgement. Tracking routes remain on
  the existing EXEC retirement path; published K/E routes are consumed once.
  Disconnect cleanup also waits for EXEC retirement, so a subscription child
  cannot install a home entry after the cleanup sweep has passed. The directed
  witness proves data commit while the EXEC reply is still pending, disconnects,
  then checks all 128 subscription counts for two seconds. The preceding binary
  leaked 89–127 subscriptions in every one of 32 geometries; Redis passed.
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
They use plain `CLIENT TRACKING ON`; option combinations have the separate
correctness coverage described above.
**48 equal, 112 lower, zero higher.** Thus none of the requested ordinary
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
| SET | 1680 | 1680 | 2634 | 2600 |
| INCR | 2131 | 2131 | 3384 | 3349 |
| MGET | 10220 | 10193 | 22992 | 22875 |
| MSET | 16690 | 16679 | 22721 | 22553 |

`docs/clientcompat/command-totals.csv` contains every arm/cell, and
`command-sites.csv` attributes all 868 changed symbol rows. The ordinary read
handler is unchanged. Registry PreserveCaching metadata replaces a repeated
CLIENT name comparison; writes consume CACHING and return before the irrelevant
BCAST lookup. Cold EXEC code is isolated in clientcompat.cc. The Makefile pins
measured xshard compiler budgets per namespace to prevent unrelated inline
threshold drift; trial recipes and counts are retained under `budgets/`.
Notification publication templates live in the cold compatibility file. The
notification observer checks a tracking-only route before looking up pubsub
subscribers, and checks pending EXEC subscriptions only for relevant K/E
routes. The db0 compiler budget is 161773; four bounded neighbour trials retain
why that value was selected. All 72 ordinary and 32 EXEC total changes relative
to the preceding PING correction, with every changed symbol, are retained in
`validation/subscription-keyspace-counts.json`. The final bound is judged
against PRE across all 160 cells. The disconnect correction preserves every
ordinary instruction total and symbol count from that accepted candidate; its
32 changed EXEC totals and 64 changed symbol rows are separately recorded in
`validation/subscription-close-counts.json` (compiler redistribution between
`climon_armed_gate` and `climon_conn_find`).

A separate 128-row census exercises real MULTI parsing/dispatch/retirement:
two GET or INCR children, one or several shards, tracking off/on, 1s/2s,
normal/db0, atomic 0/1, batches 1/4 transactions. All EXEC scopes add work:
**+214 to +1158.25 instructions per transaction**. Preparation adds ACL shadow
checks and receipt selection; tracked execution records version observations;
retirement applies committed IO effects, replays own writes in child order,
and promotes or cancels receipts. `session-totals.csv` gives every delta and
`session-sites.csv` attributes all 5120 changed symbol rows, including compiler
redistribution among outlined helpers. This cost is explicitly on MULTI/EXEC
and tracking control paths. `instruction-summary.json` ties both products to
the sealed server SHA-256s; retained build recipes reproduce the probes.

### Correctness validation

**Final correctness refresh in progress after the disconnect correction.**
The subscription/PING and subscription/keyspace witnesses first failed on all
32 preceding candidate geometries, while Redis passed. Their fixes pass all
32 geometries. The final disconnect witness also failed in all 32 geometries
on `1076280569`, with every pending-EXEC window certified; Redis passed. The
corrected `694fae5c73` witness and production-unit rebuild are in progress.
The 160/128 instruction census is complete with zero ordinary increases.

Older broad, Tcl, differential, tracking-order and PAD receipts are retained
as superseded evidence and are not claimed for the final SHA above. Final
delivery requires all 150 requested jobs plus prerequisites, every declared
leg, both differential engines, both Tcl modes, all five POST/PAD witness
matrices, 83 harness tests, and all 55 freshness checks on the sealed final
artifacts. No throughput measurement is part of this campaign.

Earlier failures are retained, not counted as passing evidence:

* Four legacy assertions in the initial split/armed feature jobs expected
  UNPAUSE to bypass ALL and SSUBSCRIBE to fail at queue time. `climon2.py` now
  proves WRITE unpause and ALL postponement; `pubsub.py` checks QUEUED followed
  by the exact DENY BLOCKING EXEC error and no actual subscription. Complete
  replacement jobs passed 34/34 split and 35/35 armed rows before the final
  rebuild. AT15's refusal check was also replaced by admission controls and
  its exact RESP2 assertion is reused by the oracle-judged multi-controls job.
* The first full tracking-order run reached 6 × 864 passing candidate cases
  before the unchanged 900-second deadline. Idle owners and the waiting IO
  could each park for 50 ms per TRACKING ON. The final cold owner wake and
  pending-ack 1 ms polling change fixes that delay; the complete final job
  passed on the preceding candidate and is included in the final rerun. No test
  deadline was increased.
* One blockfix2 job could not find its unit binaries beside the sealed POST.
  The final artifact directory now links the freshly built unit executables
  and the verified blockfix hash binding. Its replacement is in the final
  broader selection.
* Two earlier harness runs each hit the existing 45-second one-slot scheduler
  deadline during concurrent correctness traffic; PRE reproduced that same
  failure. The preceding unchanged self-test passed in isolation. One draft Tcl
  1s run failed a no-acknowledgement unsubscribe assertion and hit the script
  GC timeout during compilation. PRE reproduced unsubscribe/PUNSUBSCRIBE
  races in 6/20 bounded mode/trial legs, including the same assertion. Both
  preceding Tcl modes passed unchanged. `pre-pubsub-control.json` retains the trials.

The superseded broad ledgers retain the four legacy assertion failures, the
tracking-order timeout and the missing-unit failure. The final verdict keeps
that history separate from the complete replacement-job receipts. Draft Tcl,
harness, instruction-census and retired-arm evidence is archived under
`docs/clientcompat/validation/` and `history/`; no assertion was weakened to
obtain a pass.

Tcl promotions: old ALL-pause precedence; CLIENT KILL SKIPME's immediate INFO
count; unsubscribe-inside-MULTI/publish-self. The transaction response-order
tracking assertion was already passing. `tcl-inventory.json` records named
known failures/skips in pause, tracking, introspection, info-command and multi.
Tracking #11715 also depends on tracking-table eviction/cron and stays skipped;
FLUSHDB-in-MULTI stays skipped for the design reason above.

Five new `clientcompat-*` rows are collected at `tests/gate.sh:6196`, before
the quick-tier branch at line 6481 (exit at 6485):
**DQ=+5, DF=+5**, so maintainer constants should change **999/1016 → 1004/1021**.
`EXPECT_QUICK` and `EXPECT_FULL` were not edited. Tcl promotions add no row.

**NOT RUN:** full `tests/gate.sh iteration`, ABBA/performance tiers,
`flip_saturated`, the inline tailgen workload, and release-only stream/xmove
rate/size-ratio assertions and the atomic RYOW rate comparison omitted by
`GATE_PROOF_NO_RATES=1`. Those start performance
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
