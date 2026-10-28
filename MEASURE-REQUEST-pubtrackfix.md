## pubtrackfix

Four roots are implemented. Three are stopped under the task's explicit
owner-decision rule; this is **not a complete seven-root compatibility fix**.
No throughput or latency improvement is claimed. No performance benchmark,
ABBA/NIC measurement, full iteration, push or merge was run by this lane.

Base: `393d6ceb1`, branch `cx-pubtrackfix`. All lane commands and children use
CPUs 32–47. The gate is configured with server CPUs 32–39 and load CPUs
40–47; self-contained batteries can pin their clients with their servers. Builds
use `taskset -c 32-47 make -j16`. Listeners stay within 20300–20399. Geometry is
16 shards, ratio 6:2 for split mode. Oracle is the actual Redis 7.4.10 binary
`/home/user/Projects/redis74/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
Source and Tcl files come from `/home/user/Projects/redis`.

### Root disposition

| Root | Result | Implementation or reason stopped |
|---|---|---|
| TRACK-BCAST-BATCH | Fixed | Cold connection state accumulates keys by prefix and publication stamp; the pass boundary emits one sorted, deduplicated array per prefix. NOLOOP uses the last writer. RESP2 redirection retains the array. The state moves with the existing connection-routing node and rearms the destination's pass flag. Whole-cache invalidation preserves the pending prefix arrays. |
| PUBSUB-REPLY-OFF-PUSH | Fixed | Successful subscribe/unsubscribe confirmations clear the operation's consumed reply-suppression flag. Published frames retain their ordering relative to confirmations. Covers SUBSCRIBE, PSUBSCRIBE and SSUBSCRIBE, OFF/SKIP, RESP2/RESP3 and empty unsubscribe. |
| PUBSUB-IMPLICIT-CONSUMER-EVENT | Fixed | XREADGROUP, XCLAIM and XAUTOCLAIM emit xgroup-createconsumer only when they create a consumer. A blocked XREADGROUP emits at waiter preparation, before being woken. Consumer metadata emits no tracking invalidation; a real XADD is the positive tracking control. |
| PUBSUB-EVICT-ON-MAXMEMORY | Fixed | Bounded owner maintenance enforces the live memory budget without requiring another write. It uses the existing eviction selector, immutable/QSBR erase, notification and AOF paths, respects pinned versions and snapshots, and also evicts the empty-string key. Redis's updateMaxmemory schedules its eviction time procedure; this uses the existing owner millisecond beat. |
| TRACK-MAXKEYS-IMMUTABLE | STOPPED: deliberate restriction | The parameter is explicitly boot-latched and per IO owner. Removing its immutable bit would neither publish a runtime limit to its readers nor implement Redis's process-wide bound. Owner decision requested; no approval received. |
| TRACK-INVALIDATE-BEFORE-REPLY | STOPPED: transaction tracking architecture | The first push is produced by premature enrollment when GET's QUEUED reply retires. EXEC's earlier writes invalidate that registration. A separate probe omitting MGET still sees the push on PRE and none on Redis. Correct enrollment needs actual child execution, commit/abort lifetime and IO-owner handoff; suppressing a push would lose real invalidations. |
| PUBSUB-SUBSCRIBE-NO-DENYOOM | STOPPED: memory accounting/admission architecture | IO-local subscribe bypasses executor DENYOOM admission. Existing memory accounting excludes subscription names and client input buffers; twelve upstream tests need those allocations counted. A metadata flag or maxmemory=1 special case would not fix the root. |

The three stopped roots retain their named known failures. Detailed evidence and
required decisions are in [owner-decisions.md](docs/pubtrackfix/owner-decisions.md)
and [exec-invalidation-origin.json](docs/pubtrackfix/exec-invalidation-origin.json).

### Reproduction and tests

[repro-pre.json](docs/pubtrackfix/repro-pre.json) replays every original
harness5 reproduction, on fresh Redis and PRE servers. All seven roots differ
in 1s/2s × uring/epoll. POST matches Redis for the four implemented roots in all four mode/engine legs;
PAD-A retains all seven PRE differences. The final POST and PAD replay receipts are
[repro-post-final.json](docs/pubtrackfix/repro-post-final.json) and
[repro-pad-final.json](docs/pubtrackfix/repro-pad-final.json).

The new `pubtrackfix` gate job has four public rows. Each runs the oracle and
32 candidate geometries: 1s/2s × uring/epoll × databases 1/16 × atomic 0/1 ×
read-local 0/1. Eviction tests ordinary and empty keys on separate fresh boots,
so the four rows total 160 candidate legs and five oracle legs. It compares complete typed RESP frames, including key order,
frame boundaries, duplicate suppression and blocking behavior. It does not
skip a failed observation or widen a tolerance.

31 named failures were removed from `tests/redis_tcl_passing.json`: 26 BCAST,
three REPLY OFF/SKIP, one implicit consumer and one eviction. They are now
required passes in both modes. The exact names are in
[tcl-promotions.json](docs/pubtrackfix/tcl-promotions.json).

The existing netcmd pubsub row requires late queued invalidations to flush in
the same pass and pending BCAST keys to survive a whole-cache invalidation.
Controls with the old drain order and with pending-key clearing both fail the
exact assertions; POST passes. See
[pass-boundary-control.json](docs/pubtrackfix/pass-boundary-control.json) and
[bcast-flush-control.json](docs/pubtrackfix/bcast-flush-control.json).

The final directed matrix and both Tcl modes pass on the final binary. The
BCAST pass-boundary unit also fails on the previous candidate and passes after
the flush-preservation correction. Both Tcl modes cover all 36 selected files
and all 31 promoted names. Fused mode used the pre-existing one-time MONITOR
ordering retry in unit/introspection; the original failure and successful retry
are retained. The promoted assertions passed without retries. The complete
selected affected-job list is [proof-jobs.txt](docs/pubtrackfix/proof-jobs.txt),
including `clientfix` and the public `compat2` verdict in the same run.
The driver [run-proof.py](docs/pubtrackfix/run-proof.py) invokes only explicitly
selected jobs; its `iteration` invocations select the standard differential
jobs only and report `GATE(PARTIAL)`, with no ABBA, NIC or full-tier run.

<!-- PROOF-STATUS -->
- Final affected-job run: **245 passed, 0 failed**, 36 selected jobs including prerequisites. Includes all 160 directed candidate legs and five oracle legs, 138 feature-matrix rows, all eight eviction legs, clientfix, compat2 and the focused notification/tracking/stream jobs.
- Tcl subset: both modes pass all 36 files and all 31 promoted assertions. Fused mode uses the existing one-time MONITOR ordering retry; the original failure and retry receipts are retained. The promoted assertions pass without retries.
- Final make all, every production-unit target and all 56 freshness queries pass. All 52 command-scope comparisons add zero instructions.
- Standard differential suites, PRE/PAD directed negatives, four Tcl regression plants and isolated gates_test: RUNNING; replace before handoff.
<!-- /PROOF-STATUS -->

**NOT RUN:** positive POST regression rows and Tcl promotions for the three
stopped roots, because their fixes require the owner decisions above.
Performance measurements and the full iteration remain maintainer work.
The existing reproductions for those roots were run and retain their differences.

An additional unresolved observation is retained in
[validation-corrections.md](docs/pubtrackfix/validation-corrections.md): one
intermediate run OOM-rejected a second SET after acknowledging maxmemory 0.
Its prior eviction succeeded. A bounded 128-cycle reset probe did not reproduce
it on PRE or POST; no regression attribution is claimed. The directed eviction
cases now each arm on fresh state. This report does not claim global CONFIG
publication correctness from their passing result.

[bcast-flush-audit.json](docs/pubtrackfix/bcast-flush-audit.json) also records
inherited behavior outside the fixed pass-boundary case: FLUSHDB inside MULTI
is rejected on PRE, and SET/FLUSHDB pipelines can partition into different
notification passes from Redis. This lane does not change transaction command
admission or claim identical pass partitioning.

### Command instruction proof

All **52 comparisons add zero instructions**, including after the final
BCAST flush preservation correction. The command fixture calls linked
production routines in both namespaces and both modes, at batches 1 and 32:
GET, SET, INCR, MGET, and MSET (both atomic settings for MSET). Four additional
fused read-local GET scopes cover both namespaces and both batches. The
instruction counter includes NOPs, excludes external library callees and fixture
glue, freezes clock_gettime, and requires the fixture's data/exit assertions.
These are command-scope counts for the ordinary unarmed paths, not a rate,
whole-server cycle count or a claim that enabled BCAST work is free.

| Command | normal 1s PRE → POST | normal 2s PRE → POST | DB0 1s PRE → POST | DB0 2s PRE → POST |
|---|---:|---:|---:|---:|
| GET | 936 → 936 | 1556 → 1556 | 818 → 818 | 1051 → 1051 |
| SET | 1060 → 1060 | 1680 → 1680 | 926 → 926 | 1159 → 1159 |
| INCR | 1522 → 1522 | 2142 → 2142 | 1308 → 1308 | 1541 → 1541 |
| MGET | 10190 → 10190 | 10190 → 10190 | 10334 → 10334 | 10334 → 10334 |
| MSET | 16991 → 16991 | 16659 → 16659 | 16428 → 16428 | 16096 → 16096 |

Table is batch 1, atomic 1. Full 48-cell command results and four read-local
results, function counts and fixture hashes are in
[instructions-pc](docs/pubtrackfix/instructions-pc). The counter is `docs/wave9/step_pc.c` and the fixture is `tests/wave9_scope.cc`;
source and counter hashes are in `instruction-counter.json`. The final production-input
binding is [instructions-production-binding.json](docs/pubtrackfix/instructions-production-binding.json).
An earlier header implementation added 64 instructions per atomic DB0 MSET;
it was replaced by the out-of-line eviction translation unit. The rejected
counts are retained in `superseded-command-comparison.json`.

### Arms and control interpretation

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/pubtrackfix/pre/tomokv` | `0cac9819e46cfdcb7836fd04d5ab55ef9a49e92403b13212d9d3edea8427d16f` |
| POST | `build/tomokv` | `faef9b9099cf0777685dd914571fda687ecc0f5c356191d11c02af6841f45b84` |
| PAD-A | `build/pubtrackfix/pad-a/tomokv` | `f44826532e0afe1ddbc315ac1d8d7cd721e67983ac53ca119e76d91e6ad592f9` |

PAD is **kind A: behavior twin**. It runs PRE behavior with the candidate's
inert ClimonConn map member and unreachable padding matching POST's `.text`
origin and total extent: address 133520, size 8584231 bytes. Individual function and data-section addresses come from this PRE-behavior
build and its linker; they are **not** individually matched to POST. This
limitation matters when interpreting a layout effect.
The recipe, link inputs and hashes are in [pad-a.json](docs/pubtrackfix/pad-a.json);
[arm-sections.json](docs/pubtrackfix/arm-sections.json) records the actual section
addresses and sizes for all three arms.
Locked structure sizes are unchanged. Disabled tracking allocates no pending
BCAST entries; disabled maxmemory does not enter the eviction cycle.

The four disposable regression binaries in `build/pubtrackfix/plants/` are
correctness controls, not merit arms. [plants.json](docs/pubtrackfix/plants.json)
records their hashes and exact edits: split BCAST arrays, restore PRE implicit
consumer behavior, preserve reply suppression on subscribe completion, or
return without background eviction. Each is run through the unchanged Tcl job
selection against the promoted required names.

Superseded arm source/object trees and instruction step traces were removed
after their hashes and counts were recorded. Production targets remain available
for freshness checks. Build-directory use is kept below approximately 25 GB.

### Maintainer merit request — NOT RUN in this lane

Use the gate's instrument on the scheduled quiet box. Run PRE/PRE first as a
null, then matched-load PRE/POST and PRE/PAD-A ABBA blocks (three blocks per
comparison). Record delivered rate, latency, cycles/op, instructions/op and IPC.
Rate at matched offered load decides regression; instructions and IPC explain it.
For ordinary command cells require the null to be stable and no material POST
regression. Any claimed improvement needs POST to move while PAD-A stays flat;
a similar PAD shift leaves attribution unresolved.

[merit-cells.txt](docs/pubtrackfix/merit-cells.txt) contains the **14 generic
cells plus 2s GET/SET p1/p32 null controls**. The file has been parsed by the
existing ABBA cell parser; the 18-cell receipt is `merit-cells-parsed.json`.
Use the same value size, connection count, keys, placement and offered load for
all arms, and the NIC rig for any send-path conclusion.

Additional feature cells, both modes, with identical fixture setup on each arm:

| Feature cell | Setup and witness | Decision statistic |
|---|---|---|
| BCAST writes | SET p1/p32 and MSET p1/p8, one versus two non-overlapping prefixes, 1 versus 64 tracking clients; repeat with NOLOOP and RESP2 redirect. Check key coverage and frames per prefix/pass. | Writer cycles/op and delivered operations at matched load; subscriber bytes/frames and latency. PRE intentionally has different framing, so report that semantic difference. |
| Subscription confirmations | SUBSCRIBE/PSUBSCRIBE/SSUBSCRIBE plus unsubscribe, REPLY ON/OFF/SKIP, RESP2/3; publish a witnessed message after each confirmation. | Completion latency and owner cycles per successful subscription; PRE OFF/SKIP failure is a correctness result, not a throughput baseline. |
| Implicit consumers | XREADGROUP, XCLAIM and XAUTOCLAIM with fresh versus existing consumers, Kt notifications on/off; include blocked XREADGROUP creation before wake. | Command cycles/op and notification latency with exact create counts. PRE missing events are recorded, not assigned an artificial rate. |
| Idle budget enforcement | Seed keys, subscribe to Ee events, set allkeys-lru then CONFIG SET maxmemory 1 without subsequent writes; include empty key, read-local off/on and maxmemory 0 controls. | Time to required eviction notification and recovery to an empty database, plus owner maintenance cost. PRE's missing eviction is a correctness failure. |

The feature setup above is additional to the generic cell grammar; do not insert
unsupported PUBSUB/XREADGROUP commands into the ordinary ABBA cell parser.

### Gate accounting

**DQ = +4, DF = +4.** `collect_job pubtrackfix` is at `tests/gate.sh:6022`,
before the quick-tier exit at line 6096. The job emits four aggregate public
rows; the matrix legs and promoted Tcl assertions add no public rows. The
existing netcmd pubsub row gains assertions only. Owner should change
EXPECT_QUICK **881 → 885** and EXPECT_FULL **898 → 902**. This lane has not edited
either constant.
