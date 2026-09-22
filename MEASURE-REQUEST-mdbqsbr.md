# mdbqsbr — map lifetime only

## Launch audit (before changing lifetime semantics)

Worktree `/home/user/Projects/cx-mdbqsbr`, branch `cx-mdbqsbr`. Launch HEAD
`f3cf0fc915386fc6b692ac85a0d12ffd86d040ea` is `b8fe404e2` (landed mdbstamp)
plus a gate reference-binary update only. PRE is built from that HEAD with the
default release Makefile flags. No server, gate, load generator, counter run or
performance measurement is authorized in this lane. All compilation uses
`taskset -c 112-127 make -j16`; eight-core units use `112-119`.

Reverified: `multidb.h:33-40` increments/decrements one shared counter with SC
RMWs; its pointer load and all three publications are SC. The counter protects
only reclamation. `multidb.cc:22-92` retires only at publication and clears only
on global reader count zero. `prepare_publish` reserves before the transaction's
non-failing commit. AOF record precedes publication. The mdbstamp regular-range
specialization and both stamping overloads must remain unchanged.

### Complete reader and participant inventory

These are launch line numbers, recorded **before** implementation. `Read` retains
one raw immutable map only until its destructor; no caller exports that pointer.
`capture()` returns an owning 256-byte copy plus epoch. All other retained routing
state is copied namespace bytes, owning keys, or an owning transaction map.

| Reader / caller | Physical participant and complete lifetime | Existing coverage / planned safe point |
|---|---|---|
| `multidb.cc:42 capture`, `:95 logical`, `:157 multidb_stamp` | Synchronous stack; copy/scan/stamp must finish before quiescence | Covered by the calling coarse scope below; no per-read registration |
| Baseline parser `io_loop.h:3127` | Connection's physical IO; split IO, fused IO, overlap passes, RL2S IO; includes both COPY/MOVE endpoints | Ordinary IO has no scope today. Add one outer scope for each complete `run_loop` pass, before CQ/epoll callbacks and through idle sweep/wait callbacks |
| Reorder parser `reorder.cc:2400` (relocated from the supplied older anchor) | Same physical IO, including R7 fused schedules | Mirror the same outer scope in `r7_run_loop`; no changes to pause-before-stamp/admission |
| `multi.inc:587` EXEC preparation | IO dispatch stack; `state.database_map` and speculative routing map are owning copies | IO outer scope; copied map may outlive it safely |
| `multi.inc:221,2391,2457,2530,2556` WATCH logical attribution; `:2565` SWAP watch | Shard's current physical owner, ordinary commands, transactions, maintenance, expiration and blocking execution | Existing EX/fused/sweep scopes nest inside the complete owner/IO pass. Extend split EX coverage around the complete pass, including maintenance and idle sweep |
| `notify.inc:405` keyless attribution | Owner expiration/eviction/notification work, also fused control | Complete owner/IO pass; only copied DB byte retained in output |
| `blocking.inc:357` parked request remap | Owner maintenance, ordinary and reordered sweeps | Complete owner/IO pass; `Read` ends before returning; blocking registration holds owning key bytes |
| `blocking.inc:1266` resumed MOVE stamp | Connection's IO, after owner aliases are dropped | IO outer scope; preserves boundary guard and remap protocol |
| `t_server.cc:2667` INFO keyspace rendering | IO finishing scatter result or synchronous owner command; copied stats table | Whole IO/owner pass; full formatting walk completes before safe point |
| `snapshot.cc:204` snapshot/AOF rewrite admission capture | Designated physical IO, explicit SAVE/BGSAVE or save cron | IO outer scope, existing shape mutex/exclusions retained; snapshot owns its copied map |
| `snapshot.cc:945`, `aof.cc:2505` restore | Startup/recovery owners, before entering worker loops | No runtime grace acknowledgement until that physical thread reaches its first loop safe point; retained versions survive initialization |
| IO-only control, client retirement, blocking resumes, owner maintenance | Every physical worker, independent of current role and `--read-local` | Fixed participant set initialized before workers start; acknowledgements are physical-thread indexed, never IO/EX role indexed |
| Park / resume / IO↔EX conversion / teardown | Same physical participant, even while role functions return | No parked/even/self exemption. Waits already have 50ms ceilings. First next pass acknowledges only after previous stack unwinds; role changes do not reset acknowledgements |
| Startup main, serverless fixtures, standalone `DatabaseMap` | Cold lifetime domain; no concurrent loop acknowledgement permitted for an unscoped cold reader | Unbound maps retain all obsolete versions until destruction. Bound server fixtures may read outside loops only while they do not advance grace concurrently, or explicitly use the same coarse scope. No assumed tid 0 |
| Shutdown / destruction | Stop and join every worker before destroying Server/DatabaseMap | Destruction owns the final grace after joins, including any participants that exited without a final acknowledgement; no map references may escape destruction |

Existing `ClientWorkScope` uses odd/even release stores and nested scopes do not
change the outer value. Its Client lifetime reaper (`io_loop.h:5483`) relies on
the acquired ROB Done edge. That proof and implementation stay intact; its
skip-even/skip-self rule will **not** be reused for map reclamation.

## Planned publication proof and memory guarantee

Use a monotonically increasing retirement request. A writer initializes the map,
release-stores the pointer, then release-publishes the request. Every physical
participant must acquire that request at a coarse safe point with an even
`client_work_epoch`, then release-acknowledge that exact request. The reaper
acquires **every** acknowledgement before freeing that generation. Acknowledging
also makes publication happen-before the participant's next acquire map load.
Thus entry racing publication either has an old acknowledgement (cannot free),
or has acquired publication (cannot load the retired version). An even epoch
sample alone supplies no evidence. A nested safe point cannot acknowledge while
the outer scope is odd. The publishing worker is included. No execution drain is
part of this argument.

The maintenance gate must precede any cold-state dereference, argument expansion,
locking or full participant scan. Only physical worker 0 scans; all workers
acknowledge. Existing loop progress, including bounded idle waits, drives the
last retirement without another publication. Quiescence is progress based, not
time based. A permanently stopped participant can retain an unlimited queue
during unlimited publications; this lane claims no hard memory bound.

## Results and mainline work

The implementation and serverless checks below are complete. Live batteries and
all performance comparisons are **PENDING MAINLINE**. No measurements were run.

Gate launch arithmetic: existing core rows at lines 1242–1250, multidb unit rows
1298–1308, and 16 live/serial rows collected at 2783–2786 are all before the
quick exit at 2808. Extend existing rows only: +0 quick / +0 full = **438 / 454**.
`EXPECT_QUICK` / `EXPECT_FULL` and `tests/multidb_serial.py:20-57` remain untouched.

## Final mechanism and proof

`DatabaseMap::Read` now contains only a const map pointer. Multi-DB construction
performs one acquire load; destruction does nothing. Both endpoints and the map
epoch come from that pointer. A null pointer remains the immortal identity map.
The DB0 return is intentional specialization. Neither stamping overload nor the
mdbstamp command classification changed (the test-only second-load fault is
absent from production).

Ownership, serialization, queue, request and reclamation are in `multidb.cc` and
its existing header. A cold `State` owns the live map, `{map, request}` retirement
records and one cache-line-separated acknowledgement per physical worker.
`bind_workers(n)` allocates this before recovery/workers; DB0 skips it entirely.
Standalone unbound maps retain all versions until destruction. A bound server's
cold callers finish before their physical worker's next loop entry; unrelated
outside threads cannot call Read concurrently with loop grace. Offline tests
either use this cold rule or impersonate only stopped participants using the
same coarse scope. There is no implicit registration as thread zero.

For a publication retiring version V at ticket g:

1. Under the writer mutex, completely initialize replacement W. Reserve retirement
   capacity first; obtain the AOF record before publication where applicable.
2. Release-store W to `current_`. Append ownership of V to the already-reserved
   record and release-store g to `requested`. Set the cheap maintenance gate.
3. At the next complete pass boundary, a worker checks the gate before touching
   cold state. It verifies its **own** existing `client_work_epoch` is even,
   acquire-loads the request, and release-stores its acknowledgement if changed.
   The coarse scope then uses the existing odd/even release stores. Inner
   `ClientWorkScope`s retain the same odd epoch; an inner safe point cannot ack.
4. Physical worker 0, independent of its IO/EX role, tries the writer mutex. A
   failed `try_lock` returns immediately. With real queued retirement work, it
   acquire-loads every acknowledgement and frees only tickets at or below their
   minimum. It clears the gate only when the queue is empty. No even, parked,
   self, or changed-odd-counter exemption exists.

The happens-before edges have two distinct jobs. For an old reader, its last
dereference precedes its subsequent safe-point acknowledgement; that release
synchronizes with the reaper's acquire before deletion. For a new reader,
`initialize W -> release current=W -> release request=g -> acquire request=g
-> future Read` puts publication before its pointer load. Atomic write/read
coherence prevents that load from observing a version older than W.

If a worker was even and enters while publication proceeds, it either has not
acknowledged g (so V stays alive), or has acquired g before starting that scope
(so it cannot read V). A stale relaxed maintenance-gate read is conservative:
its acknowledgement stays old. An acknowledgement of an earlier g still orders
all later reads against that earlier publication, even after the gate clears.
Newer publications require new acknowledgements. Sampling an even epoch remotely
does not establish any of these edges; the sampled-even fault test proves the
concrete entry window opens but the C++ argument supplies the ordering proof.

Parked workers are not exempt. IO retains its outer scope through epoll callbacks
and the idle wait; EX does likewise. Existing network waits have a 50ms ceiling,
after which the stack unwinds and the next pass can acknowledge. Time alone never
frees anything. Role exit/deactivation/startup work cannot cause premature grace:
the physical participant does not acknowledge again until the next outer pass,
after those stacks finish. IO→EX and EX→IO retain the same slot and monotonic ack.
The publisher also owes this next acknowledgement; maintenance while its scope
is still odd cannot waive it. Stop/join supplies destruction's final lifetime
rule; shutdown does not pretend stopped workers can acknowledge future tickets.

The Client reaper, including its Done edge, stored epoch snapshots and self rule,
is unchanged. Broader IO/EX outer scopes can conservatively delay its readiness;
they cannot publish a nested false even epoch. Nothing in the map proof uses
DatabaseIoDrain, DatabaseExDrain, DatabaseRun or a namespace execution drain.
All those stages, dispatch/stamp guards, blocking guards, all-shard rendezvous,
snapshot/load exclusions, WATCH and group visibility remain in place.

### Progress and allocation guarantee

Ordinary loop progress, including idle timeout returns, drives acknowledgements
and worker 0's maintenance after the **last** swap. Each progressing participant
can acknowledge once and immediately enter another reader scope. They need not
be idle simultaneously. The deterministic backlog test retains the oldest reader
across **160 alternating swaps/restores**, then drains all versions with newer
readers staggered active and no further publication.

An indefinitely stopped participant can retain an arbitrarily large queue under
unlimited publication. There is **no hard cap** and no forced free, ring-size
assumption, reader wait, or fixed time grace. After progress, retired map objects
are freed and queue **size** is zero. Vector capacity remains its high-water
reservation (also needed to preserve outstanding prepared commits); it is freed
at destruction. This lane does not bound every form of memory growth. State is
56 bytes plus 64 bytes/participant, and each occupied record is 16 bytes plus its
260-byte map payload, excluding allocator rounding/overheads.

`prepare_publish` allocates State if needed, a complete map, and an extra queue
slot before returning success. Participant storage already exists before workers.
On failure the prepared object is null and the live mapping is unchanged.
Maintenance may erase earlier records between prepare and commit but never
shrinks capacity. `publish_prepared` only locks, moves ownership, appends into
reserved capacity and publishes the pointer/request; it neither allocates nor
reclaims. As before, the globally fenced transaction is the only publisher
between prepare and commit. Ordinary swap preserves journal-before-pointer order
and rolls back on map/reserve OOM or journal refusal. Restore validates the whole
permutation, handles first identity as null, and uses the same retirement path
for repeated restores. Destruction frees live/retired storage after readers join.

### Integration and actual work frequencies

| Site | Work / frequency |
|---|---|
| `src/cmd/multidb.h`, `.cc` | All ownership and reclamation. Per Read: one acquire pointer load, zero stores/RMWs, zero registration, wait or retry. Identity is null. |
| `Server::init` in `server.h` | One multi-DB allocation of State and participant array before workers; zero DB0 allocation. |
| `Server::DatabaseWorkScope` | Reuses `ClientWorkScope` and `client_work_epoch`; outer pass adds one relaxed gate load, an epoch load, odd/even release-store pair. No retirement: no sidecar/ack/scan/lock. |
| `IoLoop::run_loop` in `io_loop.h` | One outer scope per whole IO pass, covering split, fused, overlap 0/1, split read-local and IO-only work, idle sweeps/callbacks included. |
| `IoLoop::r7_run_loop` in `reorder.cc` | Same outer envelope for reordered fused IO. Split's ordinary IO loop is still baseline, including when its executor reorders. |
| `ExLoopT::run` in `ex_loop.h` | One outer scope per complete split-owner pass, including frozen control, maintenance, sweep and wait. Existing inner scopes nest rather than toggling quiescence. |
| Retirement request | One request release store and one gate release store per publication with an outgoing non-null map; pointer publication is one release store on every path. First publication needs no retirement request. |
| Pending grace | Per pass, own epoch/request/ack loads; at most one ack release store per worker per newly observed request, with coalescing across publications. Only tid 0 attempts a nonblocking writer lock and full scan, and only when work exists. No reader-side zeroing/array clearing. |

At one command per pass the added IO pair can be two ordinary **private-line**
stores per operation; at a batch of B they amortize as 2/B. They are not hidden
as a zero-cost change. Fused/existing nested scopes cease their inner store pairs;
they keep their nesting checks. Remaining costs include cold request/ack traffic,
scans and queue movement/frees during swaps. No instruction count alone is a
performance verdict.

`DatabaseMap` stays 120 bytes, counter/gate offset 32 and pointer offset 40.
The old vector footprint is padding; no embedded Server hot field moves. Offline
PRE/POST arrays agree for both variants, including Server size 105536 multi-DB /
105152 DB0 and the cfg/placement/router/threads/AOF/snapshot/flip/owner offsets.
Static assertions retain Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144 and Config 624.

## Correctness evidence (all serverless, cores 112–119)

Build commands use `taskset -c 112-127 make -j16`. The new ASAN/UBSAN and TSAN
object sets compile **every** linked command, persistence, snapshot and loop TU
with the sanitizer and the same test-hook flags; no unsanitized map library hides
accesses from a sanitized driver. JE is off in these sanitizer units. Normal
release/measurement arms use the same default JE=1 release flags as PRE.

Commands and logs:

```
taskset -c 112-127 make -j16 build/mdbqsbr-unit build/mdbqsbr-unit-tsan
taskset -c 112-119 python3 tests/mdbqsbr_checks.py build/mdbqsbr-unit build/mdbqsbr-evidence/controls
taskset -c 112-119 env TSAN_OPTIONS=halt_on_error=1:exitcode=66 setarch x86_64 -R ./build/mdbqsbr-unit-tsan all
```

ASAN/UBSAN: all 13 selections PASS, all **16** negative executions fail with
exit 1 at the named assertion. TSAN: all 13 selections PASS. Windows are forced
using callbacks/events, have bounded 5s waits, and assert they opened; none skips
or widens a tolerance. Repeated role schedules use fresh fixtures. The lifetime
fault is an actual bypass of the grace predicate in the instrumented reclaimer,
not just disabled collection; deterministic deletion assertions fail before the
final dereference. Separate no-reclaim faults exercise eventual progress.

| Assertion family | Negative mutation and observed failure (all exit 1) | Log under `build/mdbqsbr-evidence/controls/` |
|---|---|---|
| Held parser/owner/map lifetime; publishing thread included | Bypass all acknowledgements: `held map not deleted before final dereference` | `lifetime-1.log`, `owner-1.log` |
| Whole capture copy / logical scan | Same immediate-free predicate: `capture/logical retains map through last dereference` | `capture-1.log`, `logical-1.log` |
| Last-swap exact-once reclaim and empty idle gate | Disable reclamation: `last-swap maintenance frees held version exactly once` | `lifetime-2.log` |
| Entry after writer sampled even, before pointer publication | Skip sampled-even slots: `sampled-even participant still owes publication acknowledgement` | `entry-3.log` |
| Park/resume and role gap | Skip sampled-even slots: `parked/even/role-changing participant not silently exempted` | `park-3.log`, `role-3.log` |
| Nested scope retains outer-held map | Ignore odd outer epoch and publish false acknowledgement: held-map deletion assertion | `nested-4.log` |
| Actual baseline/R7 loop envelope, RL off, overlap 0/1 | Omit IO coarse coverage: `ordinary IO/owner loop covers stamping with read-local off` | `coverage-5.log` |
| Actual IO→EX→IO entries with publication in both gaps | Skip even participant: `role change cannot skip even physical participant` | `coverage-3.log` |
| 160 swaps/restores; last-writer drain with staggered active readers | Require all epochs idle, or stop reaper: `staggered active readers drain backlog` | `backlog-6.log`, `backlog-2.log` |
| Map/reserve allocation failure, refused prepared object, successful commit, maintenance between prepare/commit | Allocate in commit while all allocation is denied: `prepared commit performs zero allocations under denial` | `allocation-7.log` |
| AOF refusal leaves old epoch/map and no leaked replacement | Publish before the wrapped journal refuses: `AOF refusal leaves old mapping live` | `journal-8.log` |
| COPY and MOVE retain one version across an injected swap | Test-only second map load: `COPY/MOVE endpoints use one immutable version across forced swap` | `endpoints-9.log` |

Positive log: `controls/all-0.log`; control summary: `controls.log`; TSAN:
`tsan-positive.log`. Map new/delete counters also check complete destruction of
each fixture's versions. Allocation denial checks the actual commit arm; the
journal wrapper intercepts the actual `AofProducer::record_database_map` call.
Scope integration hooks run the real baseline/R7/EX outer loops but return before
transport work: no listener or io_uring is started. This is not a live boot claim.

Offline structural results, `structural-final.log` / `structural.json`:

* POST Read probe: one pointer load at +40, no lock instruction, memory store or
  retry. PRE fails that check with `shared reader RMW`.
* Actual linked `multidb_stamp(Server&, Op&, uint8_t)`: PRE 2 locked instructions,
  POST 0, PAD 2. Disassemblies are `tomokv-mdbqsbr-{pre,post,pad}-stamp.asm`.
* DB0 scope is `endbr64; ret`; DB0 bind returns true and quiescent returns directly.
  Enabling coarse scope in the DB0 test build fails the no-work structural check.
  A separately linked DB0 negative unit also fails the runtime assertion
  `DB0 adds no map scope, acknowledgement, or maintenance work` (exit 1), recorded
  in `db0-negative-unit.log`. PRE/POST hot layout arrays are identical.
* These structural observations make **no measured performance claim**.

Existing required serverless coverage passed:

| Selection | Result / log under `build/mdbqsbr-evidence/` |
|---|---|
| `build/multidb-unit` | PASS, including unchanged mdbstamp checks, owners, both read-local identities, WATCH/MOVE/COPY/SWAPDB/EXEC and native snapshot/AOF map replay; `multidb-unit.log` |
| `build/multidb-boundary-unit` | PASS, both modes, accept windows with RL 0/1, stamp/publication and serial boundary schedules; `multidb-boundary-unit.log` |
| `tests/multidb_serial.py --self-test` | PASS legal orders and rejection of stale-stamp oracle; `multidb-serial-self-test.log`; file unchanged |
| Core watch/lifetime/drain/route/snapshot/config/notify | All seven PASS under full ASAN/UBSAN and full TSAN: `core-{asan,tsan}-{selection}.log` |

The existing core unit Makefile target now links/copies the fully instrumented
core build. The existing multidb row includes the new schedules and their fault
controls; the new binary is an order-only dependency of that row's unit build.
There are **no new public gate rows**. Final collection lines: multidb unit 1298,
boundary 1305, live/serial collection 2787, quick exit 2810; all stay before the
exit. Arithmetic remains 438+0 / 454+0. EXPECT constants were not edited.

**PENDING MAINLINE:** all eight live multidb and eight serial-order rows; full
snapshot/AOF restore, multi_exec, blocking, notifications, FLIP/LB and Redis 7.4
differential batteries; both live boots. Reproduce correctness at **eight physical
cores, --shards 16 --ratio 6:2 --databases 16, 1s/2s × read-local 0/1 × atomic 0/1**.
Record `--overlap` and `--reorder` for every run; include 0/1 variants. The lane's
ordinary IO coverage witnesses explicitly use RL 0 and overlap 0/1; existing
boundary/store units cover RL 1, but live combinations remain pending.

## Mainline measurement request — not executed

Measurement arms are PRE (launch mdbstamp), POST (this lifetime change), the
designated stable reference, and PAD-A as the causal control. `build/tomokv` is
POST. Pair each comparison at the same **explicit** `--databases 1` or `16`.
Compare POST/PRE, POST/stable reference and PAD/PRE with ABBA and corresponding
identical-arm null controls. Do not infer a win from the structural RMW count.

Release command/flags for PRE and POST:

```
taskset -c 112-127 make -j16
# -std=c++20 -O2 -g -Wall -Wextra -march=native -pthread; JE=1
# Existing per-TU inline/large-unit budgets and dual-namespace link order unchanged.
```

The DB wrappers in `build/mdbqsbr-arms/db{1,16}-{pre,post,pad,reference}` only
`exec` the corresponding binary with the fixed database count; no wrapper remains
running. They were written, never executed. Reproduce them with
`python3 tools/mdbqsbr_artifacts.py arms build/mdbqsbr-arms`. Their manifest records
**both wrapper and actual executable hashes**. The checked-in ABBA CLI has no
general server-argument option, so this avoids silently benchmarking its DB1
default as a DB16 arm. Retain actual child argv and executable hash in receipts.

Initial performance geometry comes from the recorded ABBA placements:
**32 physical server cores 0–31, load cores 32–111, no SMT; split ratio 16:16**.
The instrument derives 128 shards for that split and 256 for fused. This is the
recorded performance geometry; correctness reproductions use the eight-core
16-shard/6:2 geometry specified above. Keep 512 total connections, 2,000,000 keys,
64-byte values, P:P key distribution/distinct client seeds, 3s warmup, **20s central
window**, 5s tail, atomic 1 and overlap 1 for the requested headline cells. Pin the
same load-instance count and exact worker placement on all arms; do not let one
arm choose a different rung. Confirm saturation/headroom using the gate's own
null/PIN procedure before scoring. Its current ladder is 1,2,4,8,12,16.

Cell definitions are retained verbatim in `tests/headline_cells.txt`; use these
groups, with GET and SET scored separately:

| Cells (GET / SET) | Mode | Read-local | Reorder | Pipeline | Connections |
|---|---|---|---|---|---|
| h05 / h06 | 1s | 0 | 0 | 32 | 512 |
| h07 / h08 | 1s | 0 | 1 | 32 | 512 |
| h21 / h22 | 2s | 0 | 0 | 32 | 512 |
| h23 / h24 | 2s | 0 | 1 | 32 | 512 |
| h37 / h38 | 1s | 0 | 0 | 1 | 512 |
| h39 / h40 | 1s | 0 | 1 | 1 | 512 |
| h53 / h54 | 2s | 0 | 0 | 1 | 512 |
| h55 / h56 | 2s | 0 | 1 | 1 | 512 |
| h13 / h14 | 1s | 1 | 0 | 32 | 512 |
| h15 / h16 | 1s | 1 | 1 | 32 | 512 |
| h29 / h30 | 2s | 1 | 0 | 32 | 512 |
| h31 / h32 | 2s | 1 | 1 | 32 | 512 |
| h45 / h46 | 1s | 1 | 0 | 1 | 512 |
| h47 / h48 | 1s | 1 | 1 | 1 | 512 |
| h61 / h62 | 2s | 1 | 0 | 1 | 512 |
| h63 / h64 | 2s | 1 | 1 | 1 | 512 |

**Recorded calibration gaps:** h05/h07/h15/h31 have calibrated instance count 12;
h21/h23 have 2, all at the recorded 32-core placement. Other requested p32 entries
are `historical-unverified` with no geometry: h06=4; h08/h13/h14/h16=3;
h22/h24/h29/h30/h32=2. These are provenance, **not usable pinned results**. All 16
requested p1 IDs have **no load-floor entry**. Mainline must supply current
calibration/identical-arm controls for those cells and verify existing floors for
the DB16 regime. Do not edit away these status checks. No actual definitions for
historical p8g1/p8s0/p8s1/f8g1 were found in these two current instruments; they
remain pending mainline's original recorded definitions, not guessed aliases.

Regimes, each with unchanged arms, offered load and durations:

1. **Benefit:** DB16, no swaps, all 32 cells above at 512 connections and both p1
   and p32 saturation. This isolates removal of the shared reader RFOs.
2. **Neutral:** the identical DB1 cells. This is a paired null requiring parity;
   3% is not an allowance for a DB1 regression.
3. **Possible deficit:** DB16 with periodic and repeated SWAPDB, both the ordinary
   512-connection saturation and separately labelled low-concurrency 8-connection
   variants. Keep the original h IDs at 512; label low-concurrency variants
   `swap-low8/<id>` and freeze their own common offered load/placement. For a
   concrete 20s schedule, issue SWAPDB 0 1 at central offsets 0.5,1.5,…,19.5s
   (20 expected successful swaps); repeated-swap variants issue four ordered
   swaps at each offset (80). Use one separate control connection, excluded from
   the 512/8 reader connections and measured command denominator. Seed identical
   key/value populations in DB0 and DB1 for every swap arm so swaps do not turn
   the GET workload into alternating hit/miss populations. Preserve any resulting
   cache/working-set change equally across arms. Record actual reply/issue times,
   refusals, successful swap count and backlog. A count/schedule mismatch makes
   that comparison unusable, not a throughput win.
4. **Wider-core repeat:** request 64 physical server cores, both p1/p32 and the same
   512 connections/knob cells, to test whether RFO savings scale. Exact nonoverlapping
   server/load placement, split ratio and PIN calibration are **PENDING MAINLINE
   SCHEDULING**; only 32-core ABBA geometry is currently recorded. Do not reuse
   the 32-core floor as evidence for a different geometry or assume a win.

Retirement backlog is the number of queue records, plus retained capacity and
oldest ticket/each acknowledgement for diagnosing lack of progress. This lane
adds no INFO sampling on the hot path. Mainline can inspect writer-protected
cold state, or stop the process **outside the timed interval** to read the
debug-symbol State/vector. PRE uses `retired_`; POST/PAD use `state_->retired`.
Record start/end values and the no-more-swaps drain after participants advance.
Do not use process RSS alone as a queue count, or a fixed elapsed delay as proof
of grace. Include actual successful swap counts from the control connection.

Mainline-only invocation shape after calibration, for each fixed DB count and
each pair (shown for DB16 PRE/POST; the lane has not run this):

```
python3 tests/abbagate.py --build-reference 0 \
  --reference-binary build/mdbqsbr-arms/db16-pre \
  --candidate-binary build/mdbqsbr-arms/db16-post \
  --server-cores 0-31 --server-smt '' --load-cores 32-111 --load-smt '' \
  --only h05,h06,h07,h08,h13,h14,h15,h16,h21,h22,h23,h24,h29,h30,h31,h32,h37,h38,h39,h40,h45,h46,h47,h48,h53,h54,h55,h56,h61,h62,h63,h64 \
  --output build/mdbqsbr-measure-db16-pre-post
```

Use the maintainer's gate counter instrument for cycles/op **together with**
instr/op and IPC, rates and scored latency. Retain raw counter/command windows
and identical-arm controls. The checked-in optional `abba_profile.py` documents
wider, non-aligned diagnostic windows and labels derived counters/op approximate;
do not relabel those as exact central-window counts or a normal-gate receipt.
No instrumentation change is bundled into this lane. Any missing aligned
counter evidence remains pending rather than inferred from rate or instructions.

**Pass conditions:** benefit cycles/op decreases; for **every scored cell** POST
rate is at least PRE **and** stable reference, cycles/op does not increase, and
scored latency does not worsen. Report p1 as well as p32 with many connections.
Do not average away any deficit, including low-concurrency swap maintenance.
More than 2% identical-arm spread invalidates the comparison. A flat PAD/PRE
paired control is necessary for attributing a POST gain to counter removal;
the PAD layout limitation below prevents claiming complete address-layout control.

| Regime / all constituent cells kept separate | PRE cycles/op; instr/op; IPC | POST cycles/op; instr/op; IPC | PRE / POST / stable rate | Scored latency | Verdict |
|---|---|---|---|---|---|
| DB16, no swaps, p1 and p32 | PENDING | PENDING | PENDING | PENDING | PENDING |
| DB1 paired null, p1 and p32 | PENDING | PENDING | PENDING | PENDING | PENDING |
| DB16 periodic swaps, 512 connections | PENDING | PENDING | PENDING | PENDING | PENDING |
| DB16 repeated swaps, 512 connections | PENDING | PENDING | PENDING | PENDING | PENDING |
| DB16 periodic/repeated swaps, low 8 connections | PENDING | PENDING | PENDING | PENDING | PENDING |
| PAD-A/PRE paired control | PENDING | PENDING | PENDING | PENDING | PENDING |
| Wider-core repeat | PENDING | PENDING | PENDING | PENDING | PENDING |

### PAD construction and limits

**Kind A, behaviour twin.** Build with the same release flags plus
`-DTOMO_MDBQSBR_PAD` in `BUILD_ROOT=build/mdbqsbr-pad`. This restores PRE's actual
shared SC add/sub counter at offset 32, SC pointer load/publication and writer-only
`counter == 0` retirement clearing. It is a multi-DB counter on the original
line, not a dummy unrelated counter or a DB0 control. Candidate member layout,
cold ownership sidecar and outer ClientWorkScope coverage remain. Reclamation
requests are disabled in this build so its lifetime behavior is PRE's.

PRE .text is 7,426,003 bytes; POST is 7,435,564, a **+9,561-byte** change. The raw
PAD is 2,096 bytes shorter than POST. `tools/mdbqsbr_artifacts.py pad` relinks it
with 2,096 unexecuted NOP bytes, giving the exact POST aggregate .text size. The
receipt is `build/tomokv-mdbqsbr-pad.json`. It matches member layout and total
text size, **not each function's address, branch layout or inlining**. The extra
candidate coarse-scope work remains, so this is a limited control, not a claim
that all incidental text effects have been isolated. No kind B inverse control
is supplied: adding padding cannot restore POST's larger text to PRE's smaller
size without removing code. This limitation is explicit and performance
attribution remains pending.

### Artifact hashes

| Artifact | SHA-256 |
|---|---|
| `build/tomokv-mdbqsbr-pre` | `83581a237071801330a10ebf9c1073b8e3d4906f85e0a0bd79a8338b29dfff92` |
| `build/tomokv-mdbqsbr-post` | `5adbd64cd40023783c0c0b3f2947f25bf1565b9aa64eb694730a0e08deba454f` |
| `build/tomokv` (POST) | `5adbd64cd40023783c0c0b3f2947f25bf1565b9aa64eb694730a0e08deba454f` |
| `build/tomokv-mdbqsbr-pad` (A, padded) | `4abaf5fe67fb15d3cda48995dea021e85bebf7bc0260c3ac7de1865a70b546e7` |
| `build/mdbqsbr-pad/tomokv` (unpadded construction input) | `c8c8a9c9d8b6e343beb249ab86c90a6aea5b3e38d6d1c14ab459566fc0a4acd4` |
| `/home/user/Projects/bench-bins/tomokv-headline-b8fe404e2` | `5108148e23cdf468d46b1659a3492df8138fc6e14ddff79f711585e13d4803b4` |
| `tests/headline_cells.txt` | `d5c2b906668e4f49b4e6bed7aeee7c9610dadae3a239e333a9a2fd0f43dc1350` |
| `tests/gate_measurements.json` | `4ce1ccc69458d5b5b7bd33910fa3a7d26130e96dd9c3e667fb674a409598e4e7` |
| unchanged `tests/multidb_serial.py` | `be9779a315ebeadd9d21cea02ad35f04d923174907d220a8ed59b502dbb4b097` |

The stable reference hash was read and verified, not assumed. Wrapper/executable
hash pairs are retained in `build/mdbqsbr-arms/manifest.json`. Build and structural
receipts are in `build/mdbqsbr-evidence/`; no measurements or live results are
presented as completed. Append mainline results as `MEASURE-RESULT`.

## Review inventory and blockers

Coverage was committed before lifetime changes (`f0c9ddd28`); implementation and
initial proofs in `13298482d`; tighter role/capacity witnesses in `844f59d3b`.
Remaining blockers to landing/performance claims are mainline live gating,
missing/unverified calibration and counter evidence, the wider-core schedule,
and the PAD's lack of exact function-address matching. There is no assertion
that this candidate meets performance parity until those results exist.

The diff against b8fe404e2 includes the **pre-existing launch** reference-binary
update in `tests/gate_measurements.json`; the lane did not edit that file.
Final `git diff b8fe404e2 --stat` is recorded below. No push, no server, no gate,
no benchmark and no performance measurement was run by this lane.

<!-- final-diff-stat -->
```text
 MEASURE-REQUEST              |  24 ++-
 MEASURE-REQUEST-mdbqsbr.md   | 502 +++++++++++++++++++++++++++++++++++++++++++
 Makefile                     |  30 ++-
 src/cmd/multidb.cc           | 199 +++++++++++++++--
 src/cmd/multidb.h            |  99 ++++++++-
 src/core/ex_loop.h           |   7 +
 src/core/io_loop.h           |   7 +
 src/core/reorder.cc          |   7 +
 src/core/server.h            |  36 ++++
 tests/gate.sh                |   2 +
 tests/gate_measurements.json |   8 +-
 tests/mdbqsbr_checks.py      |  45 ++++
 tests/mdbqsbr_probe.cc       |  17 ++
 tests/mdbqsbr_unit.cc        | 406 ++++++++++++++++++++++++++++++++++
 tests/multidb_db0_unit.cc    |   7 +
 tests/multidb_unit.cc        |   4 +
 tools/mdbqsbr_artifacts.py   | 155 +++++++++++++
 17 files changed, 1509 insertions(+), 46 deletions(-)
```
