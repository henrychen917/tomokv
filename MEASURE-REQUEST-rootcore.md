# Rootcore correctness and measurement handoff

## rootcore

Baseline: `7d2f8a2051961a1942735fb6dc9b507d778e09d1`. Branch: `cx-rootcore`.
Worktree: `/home/user/Projects/cx-rootcore`. No push. Correctness servers and builds
are restricted to CPUs 16–31; servers use ports 20100–20199 and `LC_ALL=C`.
No throughput result is claimed. The broader proof is still in progress below.

### Arms and measurement request

| Arm | Executable | SHA-256 |
| --- | --- | --- |
| PRE | `build/rootcore/PRE` | `20cad68cbae07e8f8ce01b332f9a27236c500094f16221d33cb7aeae86e837e7` |
| POST | `build/rootcore/POST` | `d8cdb1dfbc1351b992ccbadb988cee74da5c0b3b6f3221b1f7ff8d58e868234d` |
| PAD-A | `build/rootcore/PAD-A` | `1728de4bc8e377581be39e1c554e0edd893c9f90c67aba3f57e55790ff26c38e` |

POST production sources are those committed in `eb1e3a7d1`, with the test-only
link-wrapper update in `a8ed915e8`. The final binary reports `a8ed915e`, clean
production sources. `docs/rootcore/arms.sha256` is the machine-readable receipt.
The final rebuild uses `CXX="g++ -gz=zlib"`, `CC="cc -gz=zlib"` to compress debug
sections. Its entire `.text` and `.data` match the first POST byte for byte;
only 16 bytes of `.rodata` change, all in the two namespaces' INFO Git revision
and dirty strings. `docs/rootcore/wrapper-rebuild-identity.json` records this
comparison. The 48-cell census was obtained from that identical executable
code before the test-wrapper rebuild and remains applicable; it was not rerun
merely for debug compression and version strings. Earlier witness receipts name
the first POST digest `c9b173b64222d38963cfffc85949c6be49e6f6d86aa8f1893793b35ab72ec780`;
final proof receipts name the delivered digest above.

PAD-A is **kind A, a behaviour twin**: unmodified PRE production objects, with
unreachable padding and an unreachable `mkdtemp` relocation. Its `.text` address
and size equal POST's, as do the PLT extents. This is a **total text-size control,
not an exact individual-function-placement or data-layout twin**. PRE `.text`
is 8,850,599 bytes at 182,960; POST/PAD-A are 8,865,719 bytes at 182,992.
`tools/rootcore_pad.py` and `docs/rootcore/pad-a.json` retain the link recipe and
section accounting. No PAD-B is provided.

Maintainer: run the requested 14 generic cells, plus 2s GET/SET at p1/p32, with
PRE/POST/PAD-A under the gate's own ABBA instrument. Compare matched offered
load, cycles/op, IPC and instructions/op. POST moving while PAD-A remains flat
supports a behavioural effect; movement shared with PAD-A does not isolate one.
The incomplete placement match limits that attribution. Pay particular
attention to the task-notify RMW's coherence cost. Performance measurements,
load generators, saturated-FLIP memtier and full iteration are **NOT RUN** by
this lane: the task reserves them for the maintainer.

`docs/rootcore/merit.cells.txt` freezes the exact 18 cells: the unchanged fourteen
from `tests/wbland_merit_cells.txt` (`h05 h06 p8g p8s d1g_l0 d1s_l0 m8g_l0
v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`), followed by
`h53 h54 h21 h22` (2s GET/SET p1, then p32). Retain the instrument's calibration,
worker floors, latency score and per-cell null acceptance band. Do not average
away a regression or infer a gain from an instruction reduction alone.

### Directed witnesses and mechanisms

Each server witness is an ordinary selected `tests/gate.sh` job. Normal directed
geometry is shards=16, eight server CPUs 16–23, ratio=6:2 in split mode and the
gate's fused boot in 1s, read-local/key-LB/client-LB/automatic-FLIP disabled.
Both network/persistence engines are declared as `uring` and `epoll` (normal
persistence). Tests do not accept an unopened risky window. JSON logs include
the actual boots, placement, hits and failures. Oracle counts below are separate
from target counts. PRE logs are in `docs/rootcore/pre`; frozen POST logs are in
`docs/rootcore/post-final`.

| Item | PRE witness | Frozen POST result | Mechanism changed | Residual |
| --- | --- | --- | --- | --- |
| 1 IO4.1-INBOX | Actual producer/drain diagnostic: client 93 and transfer 130 stranded items in 200,000 attempts each | 0 stranded in 200,000 attempts per producer, plus a separate 200,000-pass hard-assert run | `seq_cst` fence after successful queue publication and before the read-first notify check; remove FLIP-only reflag sweep | Hardware race witness is serverless; no claim of reproducing a live busy-server hang |
| 2 WAKE-FUSED | Task 361, fused 114, quiet+flush 252 stranded items in 200,000 attempts each | 0 stranded in each counting and assertion run | Each task producer uses unconditional ordering RMW `NotifyMask::publish`; the skipped read-first RMW was the source | Periodic depth repair and idle unmasked drain remain under the owner's independent-looker rule; coherence cost awaits measurement |
| 3 RULEP-LAG | Redundant guard removal, so no new PRE-red prediction | AT-PUB1/atomic unit result recorded in broader proof | Delete `atomic_publish_quiescent` and both production callers; retain ticket publisher mechanism | Existing survivor unit now opens a real two-ticket publication bracket instead of synthesizing a stale publisher |
| 4 PS4.9 | 4/4 native target legs delete an unreferenced segment, 4 risky hits | 4/4 pass, 8 hits including missing-manifest boots | Rename unreferenced native segments into a private durable quarantine; known rewrite history remains deletable; remove missing-manifest refusal | Quarantine preserves bytes; it does not infer a recovery order for orphaned files |
| 5 NO-A5 | All 16 target legs lose both local SORT STORE output and XREADGROUP pending state; 32 hits; Redis oracle passes | 16/16 targets and oracle pass, 34 hits | Reuse the existing notification pointer slot without erasing the local cross-shard marker; detach preserves the marker | All eight consumers audited; no spare flag bit and no layout growth |
| 9 flagged EVAL in EXEC | 16/16 target legs abort the first allow-oom child; 16 target hits; four oracle variants pass | 16/16 target legs × EVAL/EVALSHA × allow-oom/no-writes pass (64 target hits), plus four oracle hits | All ScriptRoute EXEC children enter script preparation inside flag-aware memory admission, as FCALL does | No execution algorithm replacement |
| 10 MISCONF | 8/8 target legs remain failed for the five-second recovery bound; both oracle policies recover and replay the failed write | Still 8/8 fail; two oracle legs pass | **STOPPED** under the algorithm freeze, detailed below | S1 remains; retrying discarded bytes needs a recovery state machine |
| 11 WAITAOF | Final PRE matrix: 32/32 target legs return the wrong fresh local ack; two oracle legs pass | Original fsync/receipt checks pass all 32 target legs. Expanded row fails all 32 targets on rejected SET NX; both oracle legs pass | AOF-only per-connection buffered-record/sequence receipts; local ack follows durable frontier; existing timer wait polls fsync readiness | **Partial, S1 remains:** redundant native post-images advance the receipt on a non-mutation; see the freeze boundary below |
| 12 FUNCTION journal | Expanded PRE: 24/24 target legs lose FUNCTION LOAD after rewrite; 24 target hits; three oracle policy legs pass | 24/24 targets and three oracle legs pass; five mutation/restart hits per leg (135 total) | Full registry post-images enter the ordered native increment control stream; replay restores each mutation in journal order | Snapshot/rewrite registry capture deliberately untouched for persistfmt integration |

Items 6–8 remain assigned to blockfix4. No blocking wake mechanism is changed.
The two edits in `blocking.inc` only supply the originating client ID to AOF
receipt contexts. No PS4.4 format change or other lane's assigned fix is included.

The final PRE inbox controls also exercise the hard assertion: client, transfer,
task, fused and quiet+flush abort on attempts 1860, 80, 260, 27 and 3139,
respectively. Their separate 200,000-attempt counting runs see 39, 260, 825, 229
and 310 stranded items. These differ from the initial PRE counts above because
this is a hardware scheduling race, not a fixed interleaving. All bounds and
observed hits are retained in `docs/rootcore/controls/pre-final`.

PAD-A was booted through the same gate interface and preserves PRE failures in
all five functional witness families: eval 16, segments 4, notify 16, functions
12 in the initial matrix, waitaof 32 failing target legs. The seven applicable
oracle legs pass. The expanded FUNCTION control also reproduces all 24 target
failures on PRE and PAD-A; its three oracle policy legs pass on each arm
(`docs/rootcore/controls/functions-expanded`). This
is evidence for PRE behaviour, not evidence for an exact cache-layout match.
Logs: `docs/rootcore/controls/pad-a`.

The inbox diagnostic uses the actual production posting and masked-drain methods
on two owned CPUs. A set hint with an empty queue is a legal state after an
unmasked drain. Each pass races queue publication against taking that hint,
then observes a synchronized cut after the producer pass: an unconsumed item
with a clear bit is a failure. Only after recording it does the harness reflag
and consume for cleanup. Each attempt must consume exactly one item. Store
pressure and bounded pauses vary the window. This is not a TSan proof or a
probability bound for all possible executions. POST counting and hard-assert
passes each use 200,000 fresh attempts for each of the five producer paths.
The final diagnostic also fails if none of those attempts reaches an empty
first drain. Its PRE rerun still fails on all five producers and POST passes
all ten counting/assertion legs (`docs/rootcore/inbox-arming`).

NO-A5's notification subscribers must observe `sortstore` and
`xgroup-createconsumer`; unsubscribed boots would not prove attachment occurred.
The SORT source/destination are verified to occupy the same shard (hash tags
alone do not establish placement in this tree). Eight `local_xshard()` consumers
were audited: three atomics preparation/finish paths, MULTI claims, snapshot gate,
local command entry, executor AOF selection and AOF key hashing. Existing
ScriptRoute fallback handling remains compatible with the preserved marker.

FUNCTION mutations serialize full registry post-images under the existing
registry mutex, before publishing the new registry generation. The writer uses
the existing ordered control-frame path and durability sequence. Replay keeps
registry mutation order across increments. Existing shard replay still installs
key post-images in parallel; it does not execute Lua or look up functions, so
these key restorations commute with registry restoration before startup
visibility. This is not a new globally sequential key replay algorithm. Costs
are O(registry size) serialization per FUNCTION mutation and AOF-only cold queue
storage. The frame kind is new; old binaries cannot replay these new records.

Read-only notification audit: `post_release` and `SnapshotManager::post_chunk`
also retain a read-first hint without this new producer fence. Their unmasked
lookers run on idle/drain-all paths. Busy-thread liveness for those paths was
**NOT RUN** (zero attempts, no measured hits); it is not presented as a reproduced
S1 or changed outside the assigned task/client/transfer producers. Snapshot work
outside this lane remains deferred to its owner.

### Instruction and layout accounting

`tools/rootcore_counts.py` links the real PRE/POST production objects into the
serverless command-scope harness and traces executed instructions. It covers
normal/db0 × 1s/2s × batches 1/32, with MSET atomic=0 and atomic=1: **48 cells**.
All final cells have zero added instructions. Complete counts, symbol sites and
SHA receipts are in `docs/rootcore/instructions`; `delta.json` and
`function-deltas.json` give the comparison and attribution.

| Command | Normal namespace delta/op | db0 delta/op |
| --- | ---: | ---: |
| GET | 0 | 0 |
| SET | 0 | 0 |
| INCR | 0 | 0 |
| MGET | 0 | -7 |
| MSET atomic=0 | 0 | -2 |
| MSET atomic=1 | -1 | -10 |

Both modes have those deltas; batch-32 totals are exactly 32 times batch-1.
The normal atomic MSET reduction is in `xshard_flush_commits`; db0 reductions
are in `xshard_prepare` (-7/-2/-9 for MGET/MSET0/MSET1) plus -1 in atomic MSET
commit flush. An initial db0 MSET0 compiler-order change added two instructions.
A db0-only likelihood annotation on the existing MSETNX predicate restores the
cheap non-atomic path without changing behaviour. Four isolated IPA-budget
trials did not solve it and were not used. Valid trial receipts are retained in
`docs/rootcore/budget-verified`; their README distinguishes discarded invalid
exploratory traces from the independently linked final census.

This is command-scope instruction evidence, not whole-server cost or a rate
claim. Notification producer wrappers execute PRE 13/15 instructions when the
bit is set/clear, a fence-plus-read-first variant 14/16, and the chosen task
publication 8/8. The latter always performs a locked RMW: fewer instructions do
not establish lower cycles. Static assembly is in `docs/rootcore/notify-cost.*`.
Client/transfer fences are on inbox publication. WAITAOF adds AOF-on receipt
allocation, mutex/bookkeeping and polling, and client-close cleanup; FUNCTION
journaling and quarantine are administrative/persistence work. AOF-off channel
receipt/journal storage is not allocated. These costs are outside the reported
command-scope cells and must not be inferred to be free.

The locked layouts remain Op=336, Client=1984, ThreadCtx=1408, Shard=1440,
FlatStore=944, Rob<64>=192, AtomicEntry=144 and Config=624. The production layout
assertions remain enabled. Optional AOF chunks/groups/owner contexts and the
AOF-only channel allocation grow; no locked object grows.

### Gate accounting and broader proof

Seven new rows are collected before the quick-tier exit: rootcore-inbox, eval,
segments, notify, functions, waitaof and misconf. **DQ=+7, DF=+7.** The owner's
baseline constants are 999/1016, so these additions alone require **1006/1023**.
`EXPECT_QUICK` and `EXPECT_FULL` are not edited. Row counting uses collector line
placement, not the word `full` in the partial invocation.

Their collector is at `tests/gate.sh:6162`; the quick exit is at line 6491.
The static source inventory confirms PRE full=1016 and POST full=1023. The seven
literal labels were added to the reviewed receipt fixture without using a run
ledger. Its check remains red **only because EXPECT_FULL is still 1016**;
missing/extra labels are both none (`docs/rootcore/ledger-fixture.log`).

`tools/rootcore_proof.py` records exact selected jobs, binary SHA and environment
for directed, main-uring, main-epoll, fused-uring and fused-epoll phases. Only
selected correctness jobs run, with `GATE_PROOF_NO_RATES=1`; this is not a full
gate pass or full iteration. The first frozen directed phase, before extending
WAITAOF with its non-mutation edge, reports seven passing rows including release
and one red MISCONF row. The later `rootcore-waitaof` job is red on the newly
witnessed residual below. The final directed phase has six passing rows (including release) and two red rows: MISCONF and WAITAOF. Broader phase results will be appended when complete.

`python3 tests/gates_test.py` has been run twice. Each attempt has 82 passing
tests and one failure: the complete single-slot scheduler fixture reaches its
existing 45-second deadline (exit 124). The second attempt ran without a build
on its CPUs. The deadline and coverage were not changed. Logs are retained as
`docs/rootcore/gates-test*.log.gz`; no all-green harness claim is made.

An isolated control reused the unchanged scheduler test on CPUs 24–27: PRE's
278 jobs passed in 44.887 seconds; POST's 285 jobs timed out at the unchanged
45-second bound (45.193 seconds including teardown). Thus the additional seven
jobs push the serial fixture over an already nearly exhausted deadline. This
is a harness/inventory failure, not a reproduced server hang. It is documented
under the owner's rule to leave non-S1 work for later; neither the deadline nor
the mandatory inventory was weakened. `tools/rootcore_scheduler.py` and
`docs/rootcore/scheduler` retain the comparison.

The final release and all targets in the production-unit build list build with
exit 0 (`docs/rootcore/rebuild.json`). The ordinary gate helper additionally
builds both live MDBQSBR arms and the blockfix cost/refusal targets. All **57**
`make -q` checks pass, including those concrete recursive build roots and extra
makefiles (`docs/rootcore/freshness.json`). The initial build's stale mangled
wrapper name was corrected in the unit and linker flag; its journal-refusal
negative control remains intact. The interrupted initial broader run is kept
in `docs/rootcore/proof-initial`, not counted as a completed proof phase.

The maxmemrace job is red on both PRE and POST because its Redis oracle's setup
expects OOM after `CONFIG SET maxmemory 1`, but receives `+OK`. The later keeper
thread's bad-fd exception is cleanup noise following that primary assertion.
All 48 target legs pass on each arm. The oracle's failure is retained rather
than changing its assumption/tolerance in this lane (`docs/rootcore/maxmem-pre`
and the final main-uring archive).

### Item 11 — remaining non-mutation receipt boundary

The expanded row first fsyncs the connection's SET, switches `appendfsync` to
`no`, and attempts SET NX on that existing key. It proves the command returns
nil, then asks `WAITAOF 0 0 1`. Redis retains `[1,0]`; POST returns `[0,0]` in
all 32 target legs (both modes, engines, namespaces and atomic settings).
Every leg reaches this risky moment; both oracle legs pass. PRE cannot reach
the later assertion because its first fresh-ack check already fails. Logs are
in `docs/rootcore/controls/post-waitaof-noop`.

`aof_record_local_op` emits post-images from command write metadata, regardless
of whether the handler actually mutated a key. The existing scatter/group
contract likewise records selected write candidates. A sequence receipt tied
to these native records is therefore conservative relative to Redis's last
command that actually propagated. A reply-based SET NX exception would leave
other no-ops, errors and mixed script/EXEC cases with the same problem.

Smallest general proposal: supply a per-command mutation outcome from the
existing owner-side mutation boundaries, including in-place collection and TTL
updates, script children and grouped writes; use that outcome to attach client
receipts only to actual mutations while allowing redundant native frames to
remain. Error replies cannot alone determine the outcome because a script may
write before raising an error. The layout must remain fixed, and the AOF-off
path must retain zero added instructions. This requires a mutation-to-journal
contract across handlers/stores that this baseline does not expose. It is
**STOPPED under the algorithm freeze** rather than adding per-command heuristics.
The new strict check remains in the default row; item 11 is not declared closed.

### Item 10 — STOP under the algorithm freeze

MISCONF-NEVER-CLEARS reproduced in all eight declared PRE legs: `1s`/`2s`,
`uring`/`epoll`, `appendfsync everysec`/`no`. Each leg observed one real failed AOF
write and a subsequent MISCONF reply. The test restored the process's file-size
limit and waited five seconds: none recovered. Redis 7.4 recovered in both policy
legs, accepted a later write, and recovered the write that originally encountered
the failure after restart. Witness: `docs/rootcore/pre/misconf-verified.log.gz`.
The job is `rootcore-misconf`, run through the ordinary gate job selector.

The present writer cannot safely implement a cron retry by clearing `failed_`:

- `AofManager::drain_producer` deletes a normal-engine failed chunk and retires
  its channel entry. `write_frame_normal` has already advanced the shard sequence
  and truncates to the last complete logical-record boundary, potentially before
  successfully written prefixes of a large value.
- `on_io_complete` destroys failed io_uring requests, their remaining iovecs and
  owned chunks. After outstanding requests drain it truncates to a safe boundary.
  A later successful write cannot reconstruct those discarded bytes.
- `fail()` clears `recording_`. `record_bytes`, `seal`, `resolve_groups` and the
  group-post loop may abandon serialization of an already installed value. A
  writer-only retry therefore does not cover records spanning multiple chunks.

Smallest proposed change: a recoverable-write-error state distinct from a fatal
format/allocation error; retain failed normal frames and io_uring requests with
exact remaining offsets; keep admitted owners' serialization/posting alive;
retry retained work on the existing writer's cron service; clear MISCONF only
once the retained writes succeed. The normal stream sequence must advance only
on success. Recovery must preserve the existing large-record token, GCMT
ordering, shutdown refusal and fsync receipt rules. New witnesses must force a
failure partway through a multi-chunk record and between grouped fragments and
GCMT, then verify replay after recovery on both engines and policies.

This adds an error-recovery state machine across producer serialization and
writer ownership. Per the task's explicit architecture/algorithm freeze, that
change is **STOPPED, not implemented**. The S1 refusal remains on POST. Clearing
the flag or retrying only later chunks would introduce acknowledged record loss.
The final proof will retain the failing POST row rather than relabel it a pass.
