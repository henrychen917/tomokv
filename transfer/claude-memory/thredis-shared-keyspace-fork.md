---
name: thredis-shared-keyspace-fork
description: "New refactor fork 2s-shared-keyspace-dev — logical bucket ownership over ONE shared keyspace (no key-copy migration, cheap EWMA, lock-borrow cross-shard)"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Fork `2s-shared-keyspace-dev` created 2026-07-19 off stable 194b98c91 (THredis-v13-2s, 2s fork),
pushed to origin. Big-refactor idea from the user (henry):

**CORE IDEA:** Replace physically-isolated per-worker shard dbs (`server.exThreads[ex_id].db[]`)
with ONE shared keyspace that workers own at BUCKET granularity. Keys never physically move; EWMA
rebalance = reassign bucket->worker ownership (drain-fence, NO copy) instead of copying keys. Hot
path stays 100% lock-free (each bucket has exactly one owner at a time); a lock is acceptable ONLY
during the rare migration/handoff window. Also opens new cross-shard options (lock-borrow multiple
buckets to run a multi-key command in one worker, potentially cross-shard atomicity/MULTI).
MOTIVATION: makes EWMA resharding cost O(1) ownership flip + fence instead of O(keys) copy.

**MY DESIGN READ (to validate against the arch map, agent running):** the shape is a per-bucket
dict array = exactly Redis 8's `kvstore` abstraction (array-of-dicts, one per bucket). keyspace =
kvstore of TOMO_BUCKETS(4096) bucket-dicts; ex_bucket_table[b]=worker already exists as the router.
Worker touches only owned buckets => exclusive => lock-free. Handoff = drain W1's in-flight on b,
release-store ex_bucket_table[b]=W2, acquire-load on W2 (migHoldIfDraining largely reusable, minus
the copy). HARD PARTS: (1) kvstore-level aggregate state (key_count/rehashing list/cursor) races
across workers -> make per-worker or atomic; (2) keyspace-wide ops (DBSIZE/SCAN/KEYS/RANDOMKEY/
FLUSHDB/activeExpireCycle/eviction) currently per-worker-db -> must iterate owned buckets or
coordinate; (3) NUMA locality of bucket-dicts after handoff; (4) audit every single-writer-per-db
assumption. STAGED PLAN (each validatable with the new harness/ gates): S0 introduce bucket-dict
array with STATIC 1:1 worker<->bucket-range ownership (== today's behavior, de-risk the data-structure
change, prove byte-exact+perf-neutral); S1 dynamic ownership = ownership-flip resharding replacing
the physical copy (cheap EWMA); S2 fix keyspace-wide ops; S3 (new capability) lock-borrow cross-shard.

*** RE-ABLATE LEGACY OPTS UNDER NUMA ARCH (user 2026-07-20): all prior optimization/micro-arch
work must be RE-TESTED under the new architecture as stages land — verdicts were measured on
physical shards and may flip. Knob inventory in [[thredis-v4-tunable-apparatus]] +
[[thredis-opt-and-testers]] + [[thredis-transfer-state-2026-06-28]]. Priority re-ablations:
prefetch stages (verdicts were PROVISIONAL per [[thredis-prefetch-stage-verdicts-provisional]];
shared kvstore changes dict-walk patterns entirely), zerocopy reply (16-64KB gate; interacts w/
partition flips + ref-fence), tiered operand pool (freePendingCommand path; per-node pools?),
perthread-dirty #4 (ownership changed), multi-CDB #75 heap reply buses (role flips change CDB
topology), express-slim T3 + drain T1/T2 + fake-ring/buf D1/D3 controllers (signals may shift
under two-stage routing), MGET/setop coalesce gates (localfast changes the calculus at k>=3
same-node), io_uring reply-send + busy-poll knobs (no SQPOLL per user). Method: per-knob A/B
under the standard regimes + 2-simnode mode, behind bench_guard; retire knobs that go permanently
neutral in the new arch (endgame knob-collapse rule in [[thredis-endgame-two-versions]]). ***
*** SIMULATED 2-NODE TOPOLOGY (user 2026-07-20): also test CROSS-node mechanisms here by
pretending the 8c/1-CCD 7700X is TWO fake nodes: cores 0-3 = simnode0, cores 4-7 = simnode1
(config knob e.g. tomokv-numa-sim-nodes=2 overriding topology detection). Exercise: cross-node
partition COPY migrations, cross-node shard commands (stage-1 butterfly split), intra-node
commands/flips — full functional/correctness coverage of BOTH tiers; only the remote-memory
PENALTY is unmeasurable here (perf-faithful cross-node waits for Threadripper). Build the sim
knob early in the per-node keyspace stage so every gate runs in both 1-node and 2-simnode modes. ***
*** STANDING WORK ORDER (user 2026-07-20): CONTINUOUSLY bench + validate + stress-test every
mechanism introduced on the numa version (2s-numa-dev), treating the 7700X as a SIMULATION OF ONE
NUMA NODE (its 8 cores = one node-slice: intra-node flips, role flips, client handoff, localfast,
partition coarseness are all exercisable here; only CROSS-node behavior needs Threadripper).
Gates to run per landing: xshard_corruption/intercard/localfast, mig suite, arm_validation,
ringwrap, mass_kill_stall, version_ab vs stable — always behind bench_guard. ***
*** SCOPE + HARDWARE CORRECTIONS (user, 2026-07-20): (1) This box is a RYZEN 7700X DESKTOP
(8c/16t), NOT a laptop — fix the "laptop" framing everywhere; drift/thermal effects observed are
real but it's a desktop; still SINGLE NUMA NODE so NUMA-locality claims still unverifiable here.
(2) STANDING ORDER: any new benefit found during numa work that applies to the classic
physically-separate 2s (= main stable) gets IMPLEMENTED/PORTED to stable too. (3) MAINTAINED
VERSIONS = STABLE + NUMA ONLY, no others: 2s-shared-keyspace-dev is superseded by 2s-numa-dev
(which carries its commits); 3s/pool-fork ports are OFF the table for now; 2s-auto-threads-dev
is a port SOURCE only. ***
*** GO ORDER 2026-07-20: USER SAID "now do the plan we have" — NEW FORK NAMED "numa"
(branch 2s-numa-dev off 2s-shared-keyspace-dev tip 8798b1bf9). SCOPE LOCKED BY USER:
(a) per-node shared keyspace + two-stage butterfly routing + two rebalance tiers (as below);
(b) role rebalancing = FRONT/BACK FLIPS ONLY of the fixed pinned thread set (like the validated
auto-threads PARKED<->EX shifts) — NO thread creation/freeing ever; (c) NEW REQUIREMENT: on
EX->IO role flip the new IO thread MUST receive migrated clients (park-fence-flip conn handoff
+ steered accept toward it) — client rebalancing toward a fresh IO did NOT exist before (the
auto-threads branch only shifted roles, never moved clients); (d) NO SQPOLL anywhere; epoll or
per-thread single-issuer uring only; MSG_RING allowed as handoff doorbell later; (e) BPF
reuseport accept steering = the accept-placement mechanism. User's framing (accurate): "clusters
within a single server" — each node = a mini cluster-node with shared memory inside. BUILD ORDER:
(0) WEDGE FIX FIRST (drain-fence hold livelock — all plan machinery depends on migration paths;
diag in tmp/wedge_hunt2.out trial 3); (1) merge/port the auto-threads role-flip machinery
(2s-auto-threads-dev branch — NOT in this lineage, verified 0 symbols); (2) per-node keyspace +
coarse partitions (node_workers x small-k dicts) + two-level tables; (3) intra-node O(1)
partition flip; (4) client park-fence-flip handoff + accept steering (the (c) requirement);
(5) cross-node copy tier + lazy re-homing + first-touch. Laptop validates correctness only;
perf verdicts on Threadripper NPS4. ***

USER DESIGN DIRECTIVES 2026-07-20 (NUMA, supersede flat-shared design — "two-stage butterfly"):
(1) Shared keyspace PER NUMA NODE, not global. (2) TWO rebalance mechanisms: intra-node = O(1)
partition flip; cross-node = COPY engine (kept, demoted to inter-node mover; re-homes memory).
(3) TWO-STAGE ROUTING like butterfly interconnect: bucket -> NODE (stage 1), then node-local
table -> WORKER (stage 2); cross-shard ops split twice: cross-node first, then cross-worker
within node. (4) Adopt NUMA #2 lazy re-homing on access (owner-only ptr swap), #3 first-touch
boot/partition alloc + post-flip rehash re-homing, #4 consumer-side queue/CDB placement.
(5) Storage-dict decoupling YES but coarse — per-node sharing means few workers per node share,
so partitions per node = node_workers x small-k (NOT 16384 fine; Codex curve says 64ish total
= -1.2%). User: "makes sense?" — confirmed. IMPLEMENTATION = the new S0.2 shape (per-node
kvstore, two-level tables, partition shift); pending FIRST: wedge fix (drain-fence hold ordering
livelock — trial-3 diag: all 8 threads spin R, coordinator sleeps, 1 ARM 0 DONE; fix = fence-ack
before hold-spin or coordinator abort path; full diag in tmp/wedge_hunt2.out trial 3 incl ABRT
backtrace in s.log tail section). EWMA hot-key verdict for the record: balancer fires but hot-KEY
heat unflattened pre==post (spread 4.00 both, tp unchanged) — bucket moves can't split few hot
keys; the fix for hot keys is co-location/affinity + (future) key-grain direct move, NOT more
balancing. THREAD PLACEMENT (user asked): per-node slices = each node gets its own IO threads +
workers + partitions (mini-instance); workers pinned node-local to their partitions' memory
(first-touch); IO threads same node as the workers they feed (SPSC queue lines stay on-node);
io:worker ratio per slice from the thread-combo findings (small-value dispatch-bound -> more IO,
i4w2-style; compute/large-value -> more workers); NIC IRQ affinity -> IO cores on real hardware;
cross-node coordinator role at stage-1. Validate ratios on Threadripper NPS4.

DECISIONS LOCKED (user, 2026-07-19): (1) CONTAINER = ONE shared kvstore per db (true single-db,
Design A) — NOT per-worker kvstores. (2) GRANULARITY = 16384 bucket-dicts = kvstore's native
cluster-slot count => num_dicts_bits=14 reuses kvstore's per-slot machinery (dict array, Fenwick
dict_size_index, rehashing list). NOTE: ex_bucket_table element stays uint8_t (it holds a WORKER id
<=64, TOMO_EX_THREADS_MAX); only the array LENGTH grows 4096->16384 (16KB). S0.1 = literally the
one-line TOMO_BUCKETS 4096->16384 (mask/table-len/chunk auto-follow; migration.lo/hi already int). (3) SCOPE = cheaper-EWMA
FIRST: deliver S0 (bucket backing) + S1 (handoff reshard); KEEP today's scatter-gather + 2-hop
cross-shard unchanged; DEFER lock-borrow/cross-shard-atomicity (S3) and full keyspace-wide-op
rework (S2) except where S0/S1 forces it. THE COST of the shared container = kvstore aggregate
state races across workers (key_count, bucket_count, non_empty_dicts, Fenwick dict_size_index,
rehashing list). RESOLUTION: partition aggregates PER-WORKER (per-owner counters, global = sum on
demand for DBSIZE) so the hot path touches NO shared cache line; make the Fenwick size-index lazy/
per-worker (only SCAN + size-weighted RANDOMKEY need it = S2); NO shared atomics on the add/delete
hot path. Container A reshard = drain bucket + flip ex_bucket_table[b] (no dict move at all, since
all dicts already live in the one shared kvstore). S0 decomposition: S0.1 DONE+PUSHED @ 6060c4d67 (TOMO_BUCKETS 4096->16384, one-line + comment;
element stays uint8; validated intercard 25/25, corruption 0/200, mig fails=0 w/ 632 keys converged
byte-exact, GET/SET ~2.63M ops/s no-regress; also fixed a PRE-EXISTING mig-harness bug = it asserted
converged=1 on POST-cutover STATUS where converged is structurally 0 [needs active=1] -> now polled
pre-cutover; + MIG_HI range scaling to bucket count). S0.2 (IN PROGRESS) = collapse per-worker
1-dict kvstores -> one shared 16384-dict kvstore per db with per-worker partitioned aggregates
(behavior-identical, byte-exact + perf-neutral gate) — the big structural change (kvstore.c aggregate
partitioning + db alloc at server.c:3439 + worker bucket-slot indexing at server.c:5335/5355). ARCH MAP (grounding): redisDb.keys
is kvstore* (server.h:1176); per-worker kvstores ex_dbs[w][dbid] (server.c:3439); copy engine to
DELETE = migApplyOne rdbLoad+dbAdd (server.c:8034) + whole 7953-8669; single-writer sites exExecFake
(12269)/SPSC(server.h:1949); keyspace-wide already-special/broken: SCAN runs on decoy (broken),
expiry/evict on decoy (banned RP-1 server.c:3403), DBSIZE/KEYS/RANDOMKEY/FLUSH bespoke.

Validation gates promoted to repo @ 194b98c91: harness/xshard_corruption.sh (200-canary integrity),
harness/xshard_intercard.sh (SINTERCARD counts), harness/mass_kill_stall.sh (teardown-stall metric
= before/after for the deferred non-blocking-dispatch fix). Hang-proof rules doc'd in harness/README.

Deferred from the crossshard work (see [[thredis-xshard-universal]]): the mass-hard-kill teardown
STALL (transient, always recovers, root = exDispatchPush IO-loop spin under saturation) — a proper
fix is non-blocking dispatch, folded into THIS refactor's scope (mass_kill_stall.sh is its metric).

*** AUTO-THREADS PORT MAP (recon agent 2026-07-20; full report in session transcript): machinery
= contiguous stack on origin/2s-auto-threads-dev (tip 07d685352), merge-base a06beb17e with numa
line; read code at ref 654a5125c. numa-dev = clean slate (0 poly symbols). CHERRY-PICK ORDER:
c91905df1(doc) -> b95248733(step1: exThreadMain->exSlice extraction) -> 347bd5d08(step2:
polyThreadMain + PARKED<->IO + anetTcpServerBindOnly dormant listener) -> 848474d03(step3:
PARKED<->EX spare via v8d engine; num_workers_alloc/_Atomic num_workers_live) -> a04ca5a0e+
e5ea5f8d0+89f82aa27(step4 balancer tomoThreadBalanceCron @12095, run_with_period(250), 6-grow/
2-shrink quorum votes, TM_BAL_SETTLE=12, p99 veto 2x&>500us, actuates ONLY tomoSpareShift EX;
never IO in v1). DO NOT re-pick the shared W3/W5/W6/AE/RP-1/ORDER-1 fixes (already on numa under
different hashes — double-apply hazard); skip 13 doc-only commits. HARD CONFLICTS: (1)
reshardRangeValid REJECTS spare deactivation (whole-range move trips "would empty src") — add
spare-slot exemption (src==num_workers slot; also dst=W>=num_workers on activation); (2)
exSlice extraction must carry numa's worker-loop edits + ops_total->tomoRelaxedBump (auto branch
uses plain +=); (3) tmLatMaybeStamp x2 reposition around dispatchGather/CS_LOCAL; (4) init
merges (spare pre-alloc + tmMigInitSlot vs fake_ring hwm); (5) server.h appends — VERIFY client
flag bit 57 (CLIENT_MIGRATING) free on numa; (6) classify EVERY numa `w < num_workers` loop:
consuming=num_workers_live (dispatchFanAll/csBuild/KEYS/FLUSH/autotune) vs control=alloc; (7)
verify localfast's all-keys-one-worker test tolerates spare slot W. v1.6 CONN-MIGRATION stack
(2be20398d,a2a85a326,792363aaa,654a5125c: tmMig* mailboxes, CLIENT_MIGRATING bit57, fd handoff
via tmMigDrainInbox/ServiceOut in beforeSleepIO, manual tomoMigrateTest knob 5/6 ONLY) = moves
conns between EXISTING IO threads only, balancer never calls it. CONFIRMED: client-migration-to-
NEW-IO exists NOWHERE => user requirement (c) = new work: wire v1.6 foundation to balancer +
steer to newly-flipped IO + BPF accept. 2s has NO WB slice; EX<->IO direct illegal (park first).
Port after wedge-fix commit lands. ***
*** MERGE-EXEC PIPELINE v1 IN PROGRESS (2026-07-21, user GO "implement the plan + new cross
shard method"; naming adopted: TIERED-TRANSLATION routing (page-table analogy, user's) +
MERGE-EXECUTION multi-key (merge-sort analogy, user's)). v1 = SINTER/SINTERCARD, knob
tomokv-xshard-pipeline default 0, dispatch-time branch in dispatchGather (like localfast; no
registry surgery). 3 stages driven from the drain like csLaunchHop2: (1) SIZES: per-shard sub
reports per-key setTypeSize into g->pipe_scard[] (no members; missing=0 => early empty reply);
(2) GATHER1: one sub gathers ONLY the globally-smallest key's members (existing per-key setmem
path); (3) PROBE chain: per remaining shard ascending-size, sub probes candidate list (in
g->pipe_cand, coordinator-written pre-push = release/acquire via SPSC) against ALL its keys
in-place (owner-legal reads), verdict bitmap back, survivors shrink; reply = survivors
(SINTERCARD: count, LIMIT clamp v1). Volume <= k_shards x |smallest|. CLOSE_ASAP mid-chain:
reads only => plain teardown (simpler than 2-hop). csGroup adds: pipe_stage/pipe_next/
pipe_scard/pipe_cand/pipe_ncand/pipe_order/pipe_verdict. Target bench: 200k/10 cross ~25x
(gather D-curve 36.9ms/op -> ~1.5ms). Differential gate: pipeline==gather byte-equal on the
intercard matrix + fuzz. ***
*** POST-FIX A/B (2026-07-21, guarded 4-round, VERIFIED binaries — after catching a stable-vs-
stable false run, see traps): mainstream PARITY (GETSET64B 1.00x, SET256B 0.99x, MGET 0.99x,
EXISTS 1.04x, RENAME 1.00x; 16KB row 0.91x = the known +-30% noisy row, disregard); localfast
0.49x ✓ re-engaged; cross set-ops fork-favored CONSISTENTLY across all 3 valid runs (SINTERCARD
0.77x twice, ZINTER-10x200k 0.74/0.77x) but UNATTRIBUTED (identical compute code; maybe key-
placement artifact) — Threadripper arbitrates. RESIDUAL FOUND: MSET-k4 fork mean 5192ms = ONE
~20s stall in 80 probes (DEL 28ms, other rounds 26ms) — NOT the wedge (transient, bounded):
during a hot-key migration the DRAINING window now stretches to ~seconds-to-100s (up to 1024
in-flight big snapshots x rdbLoad at 64/iter drain), and an in-range write HELD for that whole
window looks like a one-off 20s timeout. QUEUED FIX (P2, small): coordinator pre-fence backlog
cap — raise the drain fence only when ring in-flight <= ~64, shrinking the held window to
~64x apply-time. File under S1 work; NOT a blocker (pre-fix this was infinite). ***
*** WEDGE FIX SHIPPED BOTH VERSIONS 2026-07-20: numa e0c11f53f, stable/crossshard 7a11afb95
(cherry-pick clean; stable gates PASS at 4096 + its own stress trial 0/20 with 1a/1d in-phase —
NOTE stable harness trap: strip --tomokv-xshard-localfast flag, numa-only knob aborts stable boot
as "Module Configuration"). Full 4x battery green on numa (4x 0/20 + all 6 gates). TWO HALVES: PART 1 (A-side, below) was
necessary but NOT sufficient — post-part-1 trial showed the IDENTICAL wedge signature. PART 2
(the actual killer): migDrainB's UNBOUNDED while-drain — with a minutes-deep backlog of big
snapshots (each rdbLoad ~100ms), ONE call ran for minutes, B stopped popping its OWN SPSC queues,
any dispatch touching a B-owned key spun its IO thread => same whole-server death with A innocent.
FIX 2a: migDrainB bounded to 64 entries/loop-iteration (B alternates drain/serve). FIX 2b:
coalesce EARLY — capture defers+LWW-coalesces once ring in-flight >= 1024 (not only at 64K full),
AND migOverflowFlush(0) honors the same ceiling (else every deferred snapshot got promoted
immediately and the cap was a no-op); flush(1) at fence-ack/scan_done/CLEANUP pushes regardless
(entries maximally coalesced by then). Kills the O(n^2) snapshot amplification => B converges
fast. Diagnostic lesson recorded: EXISTS-passing-at-+255s while fixed-key MSET hung 20/20 was
P((3/4)^4)=32% key-placement luck — deterministic per key-set, probabilistic across sets. ***
*** WEDGE FIX PART 1 (A-side, still required — prior session notes): NOT the fence ordering (holds already pushed fences in-spin). TRUE CYCLE:
hot in-range collection key (200k SADDs to one set mid-COPYING) =>每 write captures FULL post-image
(multi-MB growing blob) => B's per-blob rdbLoad ~1000x slower than A's capture => 64K ring FILLS
=> A BLOCKS in migLogPush mid-command => A stops popping SPSC queues (fence sentinels too, C.2
never completes) => every IO thread eventually wedges in exDispatchPush routing to A => whole
server alive-but-dead at 100%. PRE-EXISTING ON STABLE TOO (identical code; fork's 256-bucket
chunks just 4x'd the hot-bucket-in-range odds) => PORT-BACK MANDATORY. FIX (6 edits, server.c):
migLogPush DELETED; migLogTryPush (non-blocking, seq stamped AT PUSH so ring order == seq order,
coalesced entries consume no seq); A-private migOverflowPut/Flush deferred-capture list with
per-key LWW replace (kills the O(n^2) amplification too); capture routes via overflow when
non-empty (per-key order); BLOCKING flush only where semantics need empty defer set: fence
sentinel ack (before fence_acked store), scan_done (sticky mig_scan_wrapped + overflow empty),
CLEANUP before MIG_DONE; reset mig_scan_wrapped in reshardArm. Wait graph: A waits only on B,
B waits on nobody = acyclic. Build clean. VALIDATION RUNNING (bu25354ou): wedge_hunt2 x4 (was
~50% wedge rate) + mig gates + corruption/intercard/localfast, guarded. AFTER GREEN: commit
2s-numa-dev + push; cherry-pick to 2s-crossshard-dev, build, mig gates, push branch+stable.
Auto-threads port recon agent dispatched (Explore, read-only). ***
*** WEDGE HUNT v1 RESULTS (2026-07-20, decisive reframing): (1) NOT LOCALFAST — wedges with
localfast OFF too (A-t1 20/20 hangs; hit pattern A:1/3, B:2/3 ≈ 50% per full-sequence trial).
(2) IT IS A FULL-SERVER WEDGE, not writes-only: on-wedge diag shows PING/GET/EXISTS/SET/perworker
ALL return empty — every new connection dead. The earlier "reads fine writes wedge" was an
ORDERING artifact (EXISTS ran pre-onset, MSET post-onset). Onset = somewhere in/after the later
full_seq phases (RENAME ping-pong or EXISTS t20 window); wedged trials burn huge timeout time.
crash=0 always — server alive-but-unresponsive, PERSISTENT (100s+, unlike the known transient
mass-teardown stall). Fork-only (stable 0 wedges ever in same harness; fork delta now = 16384
buckets ONLY since localfast exonerated... but note memtier MGET-k8-FIXED-keys phase = hot-key
storm that makes reshardAutoTune AUTO-ARM (EWMA bench proved both versions arm on such storms;
fork chunk=256 buckets vs stable 64, same 1/64 fraction) => STRONG HYPOTHESIS: wedge = fork
auto-migration mid-flight interacting with later phases (check serverLog tail for ARM without
DONE at wedge time!). (3) gdb attach produced NOTHING — likely yama ptrace_scope=1 blocks
sibling attach; sudo needs password (blocked per user-autonomy memory). HUNT v2 DIAG DESIGN
(next step): phase-by-phase timestamps + 2s-ping after each phase (find onset phase) + grep
server log reshard ARM/FLIP/DONE at wedge (mid-migration?) + /proc/$PID/task/*/{comm,stat,wchan}
sampled twice 1s apart (spinning thread = R+utime-climbing, identifies exDispatchPush spin vs
worker spin vs all-sleeping deadlock; thread comms are named) + ss -ltn Recv-Q (accept backlog)
+ THEN kill -ABRT $SPID (redis crash handler logs a backtrace + thread names to s.log) + tail
s.log. Run localfast OFF (simplify), 4 trials. Previous wrong framing for the record: ***
*** OLD FRAMING (partially wrong, kept for history): (2026-07-20, guarded run): on a guard-verified QUIET box
(load 1.19 at start; harness/bench_guard.sh @8798b1bf9 — USER RULE: always guard, Codex runs
concurrently on this box), 4-round version_ab: fork MSET-k4/DEL-k4 wedged in ~3/4 ROUNDS (20/20
and 15/20 calls at full 20s timeout; EXISTS-k4=26ms fine EVERY round; crash=0; stable=26ms all
rounds). Codex-contention theory DEAD for this bug (drift theory still stands for throughput
noise). FACTS: multi-key WRITE gather groups (cs_write coalesced: MSET/DEL k=4 fixed keys
ab:x1-4/wq:*) wedge persistently after the full phase sequence [4 memtier phases incl 16KB +
MGET-k8 R storm -> key discovery -> colocated-SINTER x20 (CS_LOCAL) -> 200k cross seeds ->
SINTER/SINTERCARD cross -> ZINTER x2 -> RENAME-cross-64KB ping-pong x100 -> EXISTS-k4(fine)];
simple/storm-only sequences (repro1/repro2) do NOT arm it; single-key writes fine (memtier SET
millions); reads all fine. Fork-only delta = 16384 buckets + localfast. HUNT PLAN (script it
as tmp/wedge_hunt.sh): bisect arming phase on quiet box, arms in order: (1) full seq with
localfast OFF from boot (kills CS_LOCAL incl. accidental MGET-k8 all-same-worker groups) —
wedge? -> if STILL wedges, not localfast: (2) rebuild fork TOMO_BUCKETS=4096 (one-line) full
seq -> isolates bucket-count; if (1) no wedge -> localfast implicated -> minimal arm = which
phase + localfast. ON-WEDGE DIAG (before kill): PING, GET single, EXISTS-k4, single-key SET,
MSET 2-key, DEBUG RESHARD PERWORKER twice 0.5s apart (which worker stalled), INFO clients,
THEN gdb -p $SPID 'thread apply all bt' (check gdb exists) -> which thread waits where =
root cause. Scripts: tmp/version_ab_r2.sh (full seq), tmp/mset_wedge_repro{,2}.sh; stable
binary tmp/wt-stable @9a37e7ffd. Suspect surface for the record: CS_LOCAL group teardown
poisoning per-iotid pooled subs / pending_ex list, OR 16384-bucket interaction in coalesced
write-sub build (csBuildCoalescedSubs), OR RENAME-2hop x100 leaving group state that blocks
write groups specifically. EXISTS uses the same coalesced builder WITHOUT cs_write and is fine
=> the delta is in the cs_write/append_extra/write-sub path or what write groups uniquely wait
on. DO NOT bless/bench the fork until root-caused + fixed + guarded version_ab clean. ***
version_ab.sh round-1 fork arm: MSET-k4 + DEL-k4 wedged PERSISTENTLY (every call hit the 20s
timeout for 400s) while EXISTS-k4 (read, seconds earlier) + all prior phases were fine; round-2
identical sequence clean. NOT localfast: repro2 (MGET-k8 random storm + concurrent write probes,
3s timeouts) got 3 TRANSIENT hangs in 1/3 trials with localfast OFF (0/3 with ON, 0/2 stable —
weak stats). Simple sequences (repro1, 8 trials) never repro. Signature: coalesced write groups
(cs_write rows) stall; reads fine; recovers post-storm in the transient form. NEXT STEP: loop the
FULL version_ab fork sequence (4 memtier phases incl 16KB + MGET-k8 storm, key discovery, seeds,
SINTER-colocated, cross SINTER/SINTERCARD/ZINTER, RENAME-cross-64KB ping-pong, EXISTS, then
MSET/DEL probes) with a wedge detector that on hang runs diag (PING/EXISTS/perworker-ops DURING
the wedge, distinguishes server-wedge vs cli/connect artifact) then gdb -p (thread apply all bt)
before kill. Scripts: tmp/version_ab.sh, tmp/mset_wedge_repro{,2}.sh; stable binary at
tmp/wt-stable (worktree @9a37e7ffd). ALSO: laptop A/B drift floor ±15-30% BETWEEN arms even
interleaved (same-code phases read 0.74-1.46x!) — mainstream fork-vs-stable parity claims need
Threadripper or 6+ alternated rounds; only within-arm-controlled rows are trustworthy (localfast
0.51x co-located = real, confirmed twice). ***

CODEX RECON RESULTS (2026-07-20, read-only; full report in session; trees are worktrees of
/shared/Projects/tomokv-stable/.git, all forked from OUR 194b98c91):
*** S0.2 DESIGN REVISION (biggest steal): Codex's shared-db experiment MEASURED the dict-count
curve on cache-resident GET/SET: dict-per-routing-bucket (= our planned 16384 dicts) = -17%(!);
256 parts = -2.6%; 64 parts = -1.2%; physical baseline 4.138M. => DECOUPLE storage granularity
from routing granularity: keep 16384 ROUTING buckets (fine EWMA heat), storage dicts = num_workers
x4 (rounded to pow2), storage part = bucket >> shift, ownership flips align to whole partitions
(their reshardRangeIsMovable adds part-alignment; reshardAutoTune rounds chunk up to part_size).
Their impl refs (tomokv-shared-db-experiment): KVSTORE_THREAD_PARTITIONED flag (kvstore.h:87),
per-dict _Alignas(64) atomic counts with dictSize-RECOMPUTE-and-store (kvstore.c:88-93, kills the
Fenwick), estoreCreatePartitioned (estore.c:68), aliased server.db==ex_dbs[w] (initServer ~3441),
migration engine gutted via ex_dbs[0]==server.db early-returns, RDB saves shared db once
(rdb.c:1694). Their validated results: 500k INCR across 10 handoffs exact; RDB reload exact; but
FLUSH*/KEYS/SCAN/RANDOMKEY hard-rejected, active expiry DISABLED (races), cron resize/rehash
skipped — same S2 gaps we deferred. Their S1 correctness point WE MUST ADOPT: hold READS too
during drain fence (reads mutate LRU/LFU + lazy-expire).
*** PORT FROM codex-fixes: DEBUG RESHARD STATUS migRangeChecksum is a cross-thread kvstore scan
from the IO thread = single-writer violation WE STILL SHIP (our server.c:8815-8818; our own FIND
comment warns of the class). Codex DELETED it, convergence := (active && scan_done &&
issued==applied), harness asserts post-flip per-command instead. Port this to stable + fork
(update mig_test convergence check accordingly).
*** DO NOT ADOPT: their smallest-driver set INTER (our largest-driver measured faster ~1.4x,
algebra: S*insert+L*probe <= L*insert+S*probe since insert>=probe); their lockless reshardArm
(lacks our mig_arm_lock; two-armer race open on their side). Their zset cost-model converges to
our largest-driver anyway; their argv-order NaN fold keeps the stock divergence we FIXED.
*** WEDGE: Codex trees contain NOTHING about the multi-key-write wedge (their multi-key writes
stay on scatter/gather; shared-db doc admits cross-owner multi-key = unsolved). Still ours.
*** Parallel-discovery validation: they independently found+fixed the SAME 5 bug classes
(migLog wrap near-identical, arm validation, fake-ring hwm window, ops_total atomics, RESETSTAT
rebaseline) — strong cross-validation of the external-review fix series.

CODEX TREES ON THIS BOX (user: "read for inspiration, just read don't edit or run"):
/shared/Projects/tomokv-stable (their checkout), tomokv-stable-codex-fixes (their fix branch),
tomokv-shared-db-experiment (THEY ARE ALSO BUILDING THE SHARED-DB IDEA — compare designs!).
Explore agent dispatched 2026-07-20 (read-only recon: their fixes vs ours, their shared-db design
vs our S0.2 plan, any wedge knowledge). EWMA bench (user: "test ewma with hot key gauss vs
stable"): tmp/ewma_bench.sh launched guarded (queues behind wedge hunt) — gaussian G:G 1:9 30s +
w0-concentrated MGET8 hot-set storm, fork vs stable x2 rounds, records tp/ARM-count/perworker
spread/integrity. Priors: gaussian hash-spreads (~1.0x, balancer should NOT fire); hot-KEY heat
unflattenable by bucket moves. Guarded 4-round A/B verdict table (quiet box): mainstream PARITY
(1.00x/0.99x/0.97x), localfast 0.51x holds, 16KB row still noisy, MSET/DEL WEDGE 3/4 rounds
(see OPEN BUG above; wedge_hunt.sh running: arm A localfast-OFF x3 + arm B ON x3 with on-wedge
diag + gdb thread dumps).

XSHARD-FASTER CAMPAIGN (2026-07-20, user: "test all your suggestions, send results with benches"):
results in fork's XSHARD_FAST_RESULTS.md @ 74144063c (sent to user). SHIPPED: #0 LOCALFAST
@ ab72fbe69 (discovered: same-worker multi-key reads paid FULL gather! CS_LOCAL ctype: read-only
gather-route rows (!cs_write && !has_hop2) with all keys on one worker -> single sub, full argv,
real proc, verbatim splice; knob tomokv-xshard-localfast default on; gate harness/
xshard_localfast.sh 16/16 differential; co-located SINTER 10k-pair 2.5->0.7ms/op ~3.6x, MGET
neutral). QUANTIFIED: #4 value-transfer gap size-linear 90us@64KB/1.66ms@1MB/5.97ms@4MB per op
(S0.2b unlock); #3 co-location worth ~3.5x ONLY with localfast (needs S1 + Schmitt affinity);
#5 mesh PARKED (~1us marginal 2-hop cost on loopback); #6 bloom parked. IN PROGRESS: #1 semi-join
probe prototype (25x headroom at 500k/10 skew: gather curve 74ns/member linear vs near-flat).
SEMI-JOIN DESIGN (for continuation): new CS route: SCARD-sizes round -> gather SMALLEST input
only -> ship candidates to other owners (probe subs; graft like csH2Sub internal-op or new ctype
following CS_LOCAL pattern) -> owners setTypeIsMember/zsetScore their OWN keys lock-free ->
verdict bitmaps (+scores) -> AND at reassembly. GRAFT POINTS (server.c): csMakeSub 6957,
csSubCopyFullArgv 6976, csSubExec switch ~6310 (CS_LOCAL case added after CS_EXISTS ~6407),
csReassemble switch ~7775 (CS_LOCAL after CS_KEYS), dispatchGather 6988 (localfast gate at top),
registry rows 5880-6050 (cs_write marks writes). Bench-hygiene traps hit: redis-cli arg >128KB
silently fails (use SETRANGE + verify STRLEN); ~1.3ms/iter cli spawn (subtract PING control);
unpinned reads 2x pinned (pin always). TWO MORE (2026-07-21): (1) REBUILD AFTER EVERY BRANCH
CHECKOUT in the main tree — an A/B ran stable-vs-stable because the numa binary was never rebuilt
post-cherry-pick (detected via localfast row 72==72 + `config get` empty = knob missing; the
localfast DIFFERENTIAL gate passes trivially when localfast never engages — add an ENGAGEMENT
assert to the gate); (2) Bash tool CWD PERSISTS across calls — a `cd wt-stable` leaked into later
calls and rebuilt the wrong tree; always use absolute cd in build/bench commands.

Related: [[thredis-xshard-universal]] [[thredis-v8d-migration-validated]] [[thredis-final-server-specs]]
[[thredis-sanity-gate-benching]] [[thredis-knob-philosophy]]

USER REQUEST 2026-07-21 (queued behind pipeline): PAPER-BASELINE VERSION — new branch (suggest
2s-paper-baseline off stable): ONLY the basic tomokv 2s architecture per the original THredis
paper. NO controllers (reshard auto OFF, T1/T2/T3/D1/D3 pinned to fixed values), NO CPU pinning
(float), batching/prefetch/cdb-count/ring-depth etc. SET TO STANDARDIZED FIXED constants (pick
the paper-era defaults; document each choice in a BASELINE.md). Mostly config default surgery +
disabling autotune paths; validate boots + basic gates; purpose = clean reference/ablation
baseline. Maintained-versions rule amended implicitly: stable + numa + this baseline (baseline
is a low-churn reference, not active dev).

*** DEADLINE COMMITMENT (user 2026-07-21): ALL open items implemented by 8pm TW Jul 22
(= 05:00 PDT Jul 22) + bench vs stable + validation. PRIORITY ORDER for the work sessions
(most valuable lands first if time runs out): (1) pipeline formal guarded A/B + FULL gate
battery + flip default if green; (2) ZINTER pipeline extension ((member,score) pairs ride the
probe chain; fold order stock-exact per the setops fix); (3) paper-baseline branch
2s-paper-baseline + BASELINE.md + boots/gates; (4) auto-threads role-flip port per PORT MAP
(the heavy item — 7 cherry-picks + 7 adaptations; if partial by deadline, report state
honestly); (5) pre-fence backlog cap (small); (6) guarded version_ab vs stable at the end with
everything on. Each landing: gates behind bench_guard, rebuild-after-checkout, absolute cd. ***

*** 128-CORE SERVER ARRIVES ~SAT 2026-07-25 (user): front-load EVERYTHING functional on the
7700X before then — full numa-plan implementation, 2-simnode coverage of both tiers, all gates
green, knob defaults settled — so the new box's time goes to what ONLY it can do: real NUMA
perf (NPS modes), remote-memory penalties, cross-node copy tier, per-node slice ratios,
125+ core scaling, real-NIC/deep-uring, and the full legacy-opt re-ablation at scale. Also
prep before arrival: a topology-detection path (replace sim knob with real libnuma/sysfs read),
and a first-boot bring-up script (build + gate battery + baseline sweep) so day one is
productive. ***

*** BENCH SPEC (user 2026-07-21, add to sessions 1-4 + report): (A) PINNING TOPOLOGY: single-node
(io4ex4 spread over cores 0-7) vs 2-SIMNODE pinning (node0=cores0-3 io2ex2, node1=cores4-7
io2ex2) — bench GET/SET 1:9, pure SET, MGET k8, MSET k4 under both (guarded, pinned client
8-15... client cores overlap at 2-simnode: use remaining SMT threads; document). NOTE: pre-
per-node-keyspace this measures PLACEMENT only (1 CCD shared L3) — still wanted. (B) STATIC
RATIO REFERENCE LINES: boot io4ex4, io6ex2, io2ex6 statically, same phases — these are the
"if we just ran 4 4 or 6 2 by default" reference the flip results MUST match. (C) FLIP BENCHES
(needs session-3 auto-threads port): front-heavy<->back-heavy flip-flop; record TOP SPEED
BEFORE / DURING / AFTER each flip (continuous 1s-resolution throughput sampling via DEBUG
RESHARD OPS diff polling, not just memtier Totals): flip PENALTY (during-dip depth+duration)
+ post-flip benefit + EWMA-triggered AND manual (modeshift knob) variants. ACCEPTANCE: post-
flip steady state ≈ same static boot config (flip-arrived ≡ boot-state, no hidden degradation);
flip penalty bounded (dip duration ~drain-fence window). Report all in the 8pm delivery. ***

*** SESSION 1/4 COMPLETE 2026-07-21 (ahead of schedule — deadline items 1+2 BOTH done):
04ed5eec0 pushed on 2s-numa-dev = pipeline DEFAULT ON (battery 9/9 with default on: all gates
exercised pipeline live; set differential PASS; 2x wedge stress 0/20) + ZINTER/ZINTERCARD
extension (12/12 differential incl rank-order-unsorted/WITHSCORES/WEIGHTS/AGGR-MAX/mixed-set/
NaN-inf-both-orders/LIMIT; bench 200k x 10 ms/20 PING~26: SINTER 29v266, SINTERCARD 26v595,
ZINTER 26v185, ZINTERCARD 25v605 — pipeline at measurement floor). Topo bench launched
(bhopegw29, tmp/topo_bench.sh): static ratios io4ex4/io6ex2/io2ex6 + 2-simnode (2x io2ex2
@cores0-3/@4-7 as separate instances, summed = zero-cross-traffic upper bound) x2 rounds,
guarded — the reference lines for tonight's flip benches. Session 2 (13:41): paper-baseline
branch (knob-inventory pass first!) + collect topo results into report material. ***
TRAP (3rd occurrence, now canon): `bash script 2>&1 | grep -viE ...` under run_in_background
SWALLOWS all output and exits 1 (grep -v with nothing passing). ALWAYS `bash script > out.file
2>&1` then grep the file. (Hit: pipe_test, lf_check, topo_bench.)

*** TOPO BENCH RESULTS 2026-07-21 (guarded, 2 rounds, tmp/topo_bench.out — the reference lines):
STATIC RATIOS (single inst, cores0-7, ops/s): io4ex4 GETSET=5.48M SET=4.51M MGET8=1.58M
MSET4=2.02M | io6ex2 GETSET=7.46M(+36%!) SET=4.36M MGET8=3.03M(+92%!) MSET4=2.32M |
io2ex6 GETSET=3.11M SET=2.67M MGET8=0.66M MSET4=1.03M (collapses, dispatch-starved).
=> io6ex2 = FLIP TARGET for read-heavy (matches historic i4w2 few-workers-many-io finding);
flip benches tonight: 4/4->6/2 under GETSET should converge to ~7.4M; 6/2<->2/6 flip-flop
gives max contrast for penalty measurement. 2-SIMNODE (2x io2ex2 @0-3/@4-7, summed): GETSET
5.61M (+2.4% vs io4ex4), SET 4.55M (par), MGET8 2.18M (+38%!), MSET4 2.39M (+19%) [multikey
cells r2-only: r1 simnode1 MGET8/MSET4 read 0.00 = harness flake, note honestly] => isolation
upper bound REAL and multi-key benefits MOST (smaller fan-out per instance) — direct validation
of the per-node architecture direction. ***

*** SESSION 2/4 COMPLETE 2026-07-21: 2s-paper-baseline branch CREATED + PUSHED (defaults-only
over stable 7a11afb95; BASELINE.md documents all 19 default changes: pin-mode 0 float,
reshard-min-ops 0, T1/T2/T3=0, D3=16 fixed, D1=16384 fixed, pf-w-* all 0, worker-spin 32,
pop-batch 8, zerocopy INT_MAX=off, coalesce off; num-cdb auto kept = original identity design).
Boots clean, intercard PASS, corruption 0/200. Branch lives in wt-stable worktree — REBUILD
wt-stable back to stable tip before using it as the stable A/B reference again! Deadline items
1,2,3 DONE; session 3 (18:51) = auto-threads port; session 4 = flip benches + backlog cap +
final A/B (3-way now: numa vs stable vs baseline for the report). ***

USER REQUEST 2026-07-21 (strict cross-IO ordering): worker pop order across its k SPSC queues is
loose (rotating batched scan — new cmd on q2 can jump 10 older on q1). Per-CLIENT order already
strict (FIFO per queue); this = cross-client fairness/p99. FIX DESIGN: TSC timestamp-merge —
fake->arrival_tsc = rdtsc at dispatch (thread-local, NO shared counter — never reintroduce a
global atomic sequencer); worker merges k queues as sorted streams (peek heads, pop oldest);
EPSILON-BATCH hybrid (keep popping same queue while head within eps of global min) preserves
batching; knob tomokv-strict-order default OFF until benched (head-peek cost vs fairness;
eps tunable, 0=strict merge). Invariant TSC fine on 7700X+Threadripper. Slot: session 4 if
port lands clean, else post-deadline. ALSO answered user: pipeline M-commands = zero locks
(ownership + baton-pass release/acquire via SPSC push + completion bit; atomics only
barrier/err; reads-only => trivial teardown).
REPORTING MODE CHANGE (user 2026-07-21): fixed 8pm deadline SCRATCHED — user has phone
availability; REPORT INCREMENTALLY as things land (short proactive update at each work-session
end: what shipped, numbers, what's next). The 04:54 cron becomes a rollup, not the deliverable.
Work-session cadence unchanged.
USER RULE REAFFIRMED 2026-07-21 (hard constraint): thread count FIXED boot->shutdown, flips only,
zero thread alloc/dealloc ever. Port COMPLIES for io/ex/spare (all boot-spawned; spare slot+
listener+shard pre-built; smokes verified). ONE VIOLATION REMAINS: reshardCoordinator = detached
pthread spawned PER MIGRATION (v8d-era) — every flip spawns+reaps one. QUEUED FIX (small): fold
the coordinator state machine into serverCron ticks (its waits are usleep-polls = naturally
cron-shaped; eliminates the thread entirely); alternative = one persistent boot-spawned
coordinator. Do after flip benches (don't destabilize the machinery mid-bench); gates: mig
suite + spare lifecycle smoke must stay green.

*** SESSION 3 COMPLETE: AUTO-THREADS PORT LANDED + PUSHED (7 commits, tip d2890fe1e). All smokes:
PARKED->IO live (listener accepting), PARKED<->EX full lifecycle (spare activates via live
migration, deactivates via spare exemption, dbsize exact, keys intact), balancer telemetering +
correctly restrained at 67% busy (needs compute-bound to fire). Full battery 9/9 + differential
+ 2x stress 0/20 on ported tree. Port bugs fixed en route: v12-K worker_direct_send stripped
(absent on lineage); resolver substring misfire replaced exThreads ALLOCATION with stats loop
(boot segv, caught by smoke, fixed). Loop classification done (alloc: stats folds + coalesce
scratch + PERWORKER; live: FanAll/flush/randomkey already converted by their step 3).
REMAINING for flip benches (18:51): compute-bound autonomous-fire scenario + front/back flip-flop
curves vs reference lines + flipped==booted acceptance. Then: coordinator cron-fold (queued),
pre-fence backlog cap, TSC strict-order, final 3-way A/B. ***
*** USER DESIGN CORRECTION 2026-07-21 (supersedes spare-centric flip benching): target = FIXED
FULLY-ACTIVE pool with role CONVERSION: 4/4 -> 5/3 or 3/5 -> 6/2 etc; NOT 3/3->3/4 spare wakes
(active-count changes are not the model even though thread count is constant). v1 reality:
substrate ready (ALL threads run polyThreadMain w/ dual io_slot/ex_slot identities) but control
is SPARE-ONLY + NO IO-EXIT. EX->PARKED->IO chain works today (front can grow); front-shrink
impossible until IO-EXIT = client drain to siblings (tmMig v1.6 fd-handoff foundation, manual
knob 5/6) + listener quiesce + park. NEXT MAJOR BUILD (v2 conversion): lift spare-only
restriction + IO-exit w/ client migration + balancer steers conversions; THEN the user's
flip-flop bench (4/4<->5/3<->6/2 under load, curves, penalty, flipped==booted vs io5ex3/io6ex2
refs — need io5ex3/io3ex5 static refs added). Flip bench v1 (spare shape) deprioritized; its
script tmp/flip_bench.sh also has a boot bug (empty-string arg passed to redis-server kills
boot) — fix when reworked for v2. ***
*** SANITY GATE (user 2026-07-21, strengthened): THROUGHPUT MUST TRACK MACHINE STATE. Every
bench asserts the number matches the actual runtime config: io6ex2 must read ~io6ex2 static ref,
a flip to more-IO must MOVE throughput toward the matching static ref (flipped==booted), strict-
order on must not silently tank hot path, pipeline on must show the cross-shard win. A number
that doesn't move with state = STOP, find the disconnect (knob not applied? config not live?
measuring wrong port/binary?). Campaign after strict-order: stress (wedge x N, kill-storm,
migration-under-load, ASAN) + bench (3-way numa/stable/baseline + strict-order A/B + state-
tracking assertions) + validation (full gate battery both editions). New features tested AND old
ones held. ***

*** V2 FIXED-POOL CONVERSION — FULL IMPL PLAN (user 2026-07-21 "implement flip then bench"; NO
spare-wake benching). Model: 8 threads total ALWAYS; io_threads_live run IO role, rest EX; a flip
moves the boundary by 1 (4/4<->5/3<->6/2). v1 blocker: only the SPARE has dual bindings; IO-born
have no shard, EX-born no listener => active threads can't change role. BUILD:
PHASE 1 grow-front (4/4->5/3->6/2, reuses VALIDATED legs = EX-exit bucket-migrate + PARKED->IO
  listener join): (a) allocate a dormant io binding (el + REUSEPORT listener) for each EX worker's
  potential IO slot [io_threads .. io_threads+maxgrow); give every poly ctx BOTH io+ex bindings;
  (b) generalize reshardRangeValid spare-exemption from `src==num_workers` to `src==live-1`
  (retiring the highest live worker to its neighbor); (c) new modeshift: convert highest-live EX
  worker -> migrate its range to live-2, num_workers_live--, park, PARKED->IO as next io_slot,
  io_threads_live++; (d) accounting: io_threads_live added (dispatch/drain honor it).
PHASE 2 grow-back (5/3->4/4->3/5, needs NEW IO-exit): drain an IO thread's clients to sibling IO
  threads (tmMig v1.6 fd-handoff foundation + steered accept), quiesce+close its listener (leave
  REUSEPORT group), park, PARKED->EX + migrate buckets IN from neighbor, num_workers_live++,
  io_threads_live--. This is the client-migration-to-thread requirement (c) from GO ORDER.
THEN bench: 4/4<->5/3<->6/2 flip-flop under load, before/during/after curves, flip penalty,
flipped==booted vs io5ex3/io6ex2 static refs. This is LARGE + delicate (concurrency + accounting
+ client drain); build incrementally, gate each phase (mig suite + lifecycle + task-count
constancy + dbsize conservation), report as pieces land. DO NOT claim done until benched. ***

*** V2 PLAN CORRECTION (user 2026-07-21): client handoff is a SHARED BIDIRECTIONAL primitive used
by BOTH directions, not phase-2-only. Growing front, the new IO thread must PULL ~its fair share
of EXISTING clients from sibling IO threads ON ITS NODE (else it only gets organic accepts and
the front stays imbalanced). Growing back, the retiring IO thread PUSHES its clients to siblings
before parking. So the two shared primitives are: (1) CLIENT-HANDOFF (park-fence-flip fd migration
via tmMig v1.6 foundation: mark CLIENT_MIGRATING, drain in-flight replies, EPOLL_CTL_DEL on src,
hand client struct to target IO thread via its inbox SPSC, target EPOLL_CTL_ADD; within-node) and
(2) BUCKET-MIGRATION (validated v8d engine). A CONVERSION = compose both, direction sets push/pull
+ migrate-in/out: GROW-FRONT = bucket-migrate-OUT (worker sheds range to neighbor) + listener JOIN
+ client-PULL (rebalance existing conns onto the new front thread). GROW-BACK = client-PUSH (shed
conns to siblings) + listener LEAVE + bucket-migrate-IN. REVISED BUILD ORDER: (0) client-handoff
primitive FIRST (shared, testable standalone: migrate N conns between two live IO threads, verify
no dropped/duplicated requests, in-flight replies land) — wire tmMig inbox to beforeSleepIO drain;
(1) grow-front using both primitives; (2) grow-back (same primitives, mirror). Steered accept
(BPF) is a later optimizer, not required for correctness (pull covers the existing-conn gap).
Supersedes the earlier "grow-front reuses only validated legs" framing. ***
*** ZERO-LOSS CONN MIGRATION PORTED + VALIDATED 2026-07-21 (cc8130e39 + 4 v1.6 cherry-picks
354be981c/f5ee70e12/e24c148fe/d39d6fa83). Foundation for BOTH conversion directions. Mechanism:
CLIENT_MIGRATING + quiesce fence (tmClientQuiesced: ring empty + no pending reply/write/partial;
v12-K wds fence stripped) -> source detaches client, hands struct to dest inbox SPSC, wakes dest
-> dest EPOLL_CTL_ADD on ITS OWN loop (no cross-thread epoll). Socket never closes. Trigger:
CONFIG SET tomokv-modeshift-test 6=rebalance(half most-loaded->least), 5=io-exit. VALIDATED:
raw no-reconnect socket 1M INCRs 0 gap/dup/reset across 8 migrations; memtier 48c 0 reconnects;
4 clean runs (1 unreproduced transient reset noted). Default-inert (balancer doesn't call it yet).
tmMigDrainInbox/tmMigServiceOut in beforeSleepIO; tmMigForgetOnFree in freeClient.
NEXT: compose conn-migration + bucket-migration into grow-front/grow-back conversion actuators
(4/4<->5/3<->6/2), then flip-flop bench (curves, penalty, flipped==booted vs io5ex3/io6ex2). Also
still need: dual bindings on all poly threads (EX workers need dormant io binding for grow-front),
io_threads_live accounting, reshardRangeValid generalize spare-exempt to highest-live. ***
*** BALANCER AUTONOMOUS-FIRE (2026-07-22): machinery CORRECT (telemetry/quorum/p99/restraint all
work) but CANNOT trigger on this 8c box — even BITCOUNT over 256KB values leaves EX workers at
~8% busy (dispatch-bound: workers finish faster than IO feeds them), so grow-quorum never crosses.
Autonomous-fire-under-saturation is a Threadripper-scale validation (more cores + genuine worker-
bound load). MANUAL shift path fully validated (PARKED<->EX lifecycle proven). NOTE: task-count
12->14 under load = jemalloc bg threads (allocation-triggered), NOT poly threads — our set is fixed
(coordinator-fold made poly count constant, verified 14=14=14 earlier). ***
*** FLIP MECHANISM + CONTROLLER — BUILD NOW (user 2026-07-22, after the io6ex2/2simnode bench).
Fixed-pool role conversion (4/4<->5/3<->6/2, total const). LOCALITY RULE: when flipping, take db
(buckets) + clients from NEIGHBORING SAME-NODE threads (adjacent index sharing the node; on the
1-node sim, adjacent index). GROW-FRONT (EX worker W -> IO): shed W's buckets to adjacent same-node
EX worker (neighbor), then W becomes IO + PULLS clients from adjacent same-node IO thread. GROW-BACK
(IO thread -> EX): PUSH clients to adjacent same-node IO thread, then become EX + take buckets FROM
adjacent same-node EX worker. Reuses: conn-migration primitive (cc8130e39, validated) for client
push/pull; v8d bucket migration for db; reshardRangeValid generalize spare-exempt->highest-live/
adjacent. CONTROLLER: extend the ported pressure balancer (tomoThreadBalanceCron) to actuate
CONVERSION (not spare-wake): front-pressure high + back idle => grow-front; back-pressure high +
front idle => grow-back; quorum + Schmitt sustain + p99 veto already there. Needs: dual bindings on
all poly threads (EX workers get dormant io binding for grow-front; IO threads get shard slot for
grow-back), io_threads_live accounting. Then flip-flop bench (curves/penalty/flipped==booted vs
io5ex3/io6ex2 refs). BUILD INCREMENTALLY, gate each step. ***
echo saved
*** FLIP BUILD STEPS (mapped from tmSpawnSpare 2026-07-22): S1 dual-bindings — pre-create dormant
io bindings (aeCreateEventLoop + anetTcpServerBindOnly + tmMigInitSlot) for growth io_slots
[io_threads .. io+ex-1] and pre-alloc empty ex shards for growth ex_slots; give each poly ctx BOTH
(EX-born gets a growth io binding; IO-born gets a growth ex shard). Boot-testable (behaves
identical, nothing converts). S2 grow-front actuator: migrate highest-live worker's range to
neighbor (live-1), num_workers_live--, EX->PARKED, PARKED->IO at growth io_slot, io_threads_live++,
PULL clients from neighbor IO (conn-mig). S3 grow-back actuator: PUSH clients to neighbor IO
(IO-exit exists), IO->PARKED, PARKED->EX at growth ex_slot, migrate buckets IN from neighbor,
num_workers_live++, io_threads_live--. S4 accounting: io_threads_live honored by dispatch/drain
fan-outs + fence nprod; reshardRangeValid exempt highest-live (not just spare). S5 controller:
tomoThreadBalanceCron actuates conversion by front/back pressure sign. GATE each: boot + lifecycle
+ task-const + dbsize + zero-loss client + flipped==booted. Waiting on bench62 to free the binary. ***
echo saved
*** FLIP S1 DUAL-BINDING — REFINED DESIGN (2026-07-22, ready to execute). KEY: on 8c io4ex4,
configured==allowed(8) => NO SPARE (spare=0); flip is pure conversion of born-role threads.
IO_SLOT CONTIGUITY SCHEME (worked out): converting worker takes io_slot = io_threads_live at
conversion; conversions go highest-worker-first (3,2,1 for 4 workers, keep worker0 as >=1 EX);
so io_threads_live grows 4->5->6 taking CONTIGUOUS slots 4,5,6. Binding assignment: EX worker i
gets growth io binding at io_slot = io_threads + (num_workers-1-i) [w3->4, w2->5, w1->6, w0->7].
Mirror for grow-back: IO thread j (highest, excl main=0) gets growth ex shard at ex_slot =
num_workers + (io_threads-1-j). IMPLEMENTATION: (1) add io_threads_live (=io_threads init); (2)
size server.ioThreads[io_threads + spare + num_workers], ex_dbs already alloc-sized; (3) factor
tmInitGrowthIoBinding(slot)=el+anetTcpServerBindOnly+tmMigInitSlot from tmSpawnSpare; (4) EX-born
ctx (server.c:13798): set ctx->io = growth binding (not NULL), io_slot per scheme, io_listening=0;
(5) IO-born ctx (13967): set ctx->ex = growth shard (not NULL) at ex_slot per scheme. GATE: boots
IDENTICAL at io4ex4 modes-on (nothing converts; bindings dormant), all threads spawn, ping/set/get.
Then S2 grow-front actuator, S3 grow-back, S4 accounting, S5 controller. NOT rushing boot-init at
session tail (hit a boot-segv earlier from a hasty resolver); tree clean at cc8130e39. ***
echo saved
*** CONFIG MODEL REFACTOR (user 2026-07-22): REPLACE io-threads/ex-threads + all min/max knobs
(ex-threads-min/max, io-threads-min/max — REMOVE, ported from auto-threads) with a NODE-TOPOLOGY
model: (1) NODE COUNT, (2) CORES-PER-NODE. Pool per node = cores-per-node (fixed, = user's fixed-
pool rule). io/ex split within a node's core budget is either: STATIC MODE = user specifies
io-cores-per-node + ex-cores-per-node (must sum <= cores-per-node) => no flipping, booted at that
split; or DYNAMIC = specify node count + cores-per-node only, balancer flips the io/ex boundary
WITHIN each node's fixed budget (implicit bounds [1, cores-1] per type, no explicit min/max — the
node core budget IS the bound). Total threads = node_count * cores_per_node, fixed boot->shutdown.
Knob shape (proposed): tomokv-numa-nodes N, tomokv-cores-per-node C, and for static:
tomokv-io-per-node / tomokv-ex-per-node. Legacy tomokv-io-threads/ex-threads become DERIVED
(single-node: io-threads = io-per-node, etc.) for back-comat OR aliased. This supersedes the
min/max the flip controller (S5) was going to bound with — bounds come from the node budget now.
IMPLEMENT alongside the flip build (the node model defines what flips + within what budget). Also
folds in the earlier tomokv-numa-sim-nodes=2 idea: node count IS the sim/real node count. ***
echo saved
*** ALWAYS-FULL-POOL RULE (user 2026-07-22): the server ALWAYS runs at the specified total =
node_count * cores_per_node, with EVERY thread in an ACTIVE role (IO or EX) at all times. NO idle
spare / reserve / parked-resting thread. This KILLS the v1 spare concept entirely: PARKED is now
ONLY a transient micro-state during a flip's handoff fence, never a steady state. io4ex4 = 8
always-active (4io+4ex); flip to 5/3 = still 8 always-active (5io+3ex); never "7 active + 1 idle".
Consequence for the flip actuator: a converting thread goes EX-role -> (brief drain/handoff) ->
IO-role directly; it does not rest in PARKED. Remove tmSpawnSpare / spare bookkeeping / the
"configured < allowed => spare" logic; all N*C threads are born into a role and only ever flip
between roles. This + the node-topology config = the final thread model. ***
echo saved

*** FLIP ACTUATORS DONE + VALIDATED UNDER LOAD (2026-07-22, worktree flip-actuator off 2f3bc722f, commits d6398e4f2 / 90b58020f / d570f061f). GROW-FRONT (EX->IO) and GROW-BACK (IO->EX) both work end-to-end, no-load AND under memtier load, no dropped connections.
BUILD: node-topology config (tomokv-numa-nodes/cores-per-node/io-per-node/ex-per-node, min/max removed); tm_ngrow_io growth io slots reserved at boot (dormant io bindings via tmMakeDormantIoBinding); io_threads_live/num_workers_live accounting; tm_flip_ctx/tm_flip_target/tm_flip_phase/tm_flip_wslot state; tmFlipTick main-thread phase machine in beforeSleep.
GROW-FRONT (modeshift-test=7 / tomoGrowFront): highest live worker sheds its WHOLE range to neighbor w-1 (prefix move), num_workers_live-- FIRST, coordinator spare_act==2 parks it, tmFlipTick PARKED->IO, io_threads_live++. Then tmRebalanceOntoNewIo() EWMA-PULLS existing conns onto the new io thread (TM_MIGREQ_REBALANCE per over-target source; EWMA-busy weighted when thread_balance on, else conn-count). Knob tomokv-flip-rebalance (default on).
GROW-BACK (modeshift-test=8 / tomoGrowBack): highest GROWN io thread (io_slot=io_threads_live-1) runs IO-EXIT = leaves accept group + migrates ALL conns out ROUND-ROBIN (dest=dests[rr_cursor++%nd] => EVEN split, the user's requirement) + parks; tmFlipTick 3-phase: await park (io_threads_live--), PARKED->EX revive, seed top-half of neighbor w-1's range in, coordinator spare_act==3 publishes num_workers_live++. Only grown slots can grow back (native io/main have no ex binding).
THREE HARD BUGS FIXED (all load-only, invisible no-load): (1) CUTOVER SELF-DEADLOCK from cron-fold: migHoldIfDraining spins a range-write producer until DRAINING->FLIP, but the coordinator is now a main-thread beforeSleep tick — when MAIN is the producer it can't reach beforeSleep -> hang. FIX: pump reshardCoordinatorTick() from the hold spin when iotid==0 (io threads only push sentinel+spin). (2) tmCtxForIotid returned NULL for grown slots -> tmGatherLiveDests/REBALANCE dest-validation couldn't see a converted worker as a live migration target. FIX: resolve grown io_slot S to worker (num_workers-1)-(S-io_threads). (3) WORKER QUEUE-SCAN BOUND exSliceCtx.nq=io_threads+1 never covered growth slots -> a converted worker running as io thread N had its dispatch queue never drained -> replyWorking PINNED (io thread busy-polls forever, its conns wedge, memtier stalls). FIX: nq += tm_ngrow_io. Also extended per-iotid IO struct init + worker queue/freeback init + tmGatherLiveDests bound to io_threads+tm_ngrow_io (earlier handleWorkerReplies segfault on 2nd conversion). Earlier no-op bug: tm_ngrow_io computed from server.num_workers which is unassigned that early in initServer -> use server.ex_threads.
BENCH (memtier 8t/160c/pipe16, 1:9, 2M keys, srv 0-7 / load 8-15): booted-4/4 5.44M, booted-6/2 7.25M, FLIPPED live 4->6/2 6.68-6.84M aggregate (incl ~5s 4/4 warmup => steady-state ~7.1M == booted-6/2). Flip recovers the FULL front-heavy benefit online. Integrity: full 40k-key scan 0 misses under concurrent writes during flips; round-trip 4/4->6/2->4/4 returns counts exactly, db conserved, crash=0.
NOTE: grow-back seeds "top half of neighbor" so ranges aren't restored to the original even split (e.g. after round-trip w0=[0,4096) w1=[4096,10240) w2=[10240,13312) w3=[13312,16384)) — correct (0 loss) but uneven; autotuner would rebalance. EWMA rebalance used conn-count fallback in tests because busy_ewma_q4 only updates when thread_balance on (ioSlice gate) — the auto-controller (TODO) runs the balancer so EWMA engages then.
TODO: (A) AUTO-CONTROLLER = extend tomoThreadBalanceCron (4Hz quorum balancer) to ACTUATE flips by front/back EWMA pressure within node budget ("auto adjust" — user 2026-07-22 still wants this; manual knob 7/8 is the test driver). (B) merge worktree -> 2s-numa-dev. (C) then the "start 4/4, auto-grow to beat the others" bench with LIVE auto-flip. Remove TEMP debug probes already done.

*** AUTO FLIP CONTROLLER DONE (2026-07-22, commit d817c4672). tomoFlipController (server.c, ~4Hz from serverCron, fwd-decl near tomoThreadBalanceCron): the always-full-pool analog of the spare quorum balancer (which is inert with no spare). Moves the io/ex boundary within node budget on sustained EWMA pressure: FRONT (ingress events/pass EWMA >= ing_hi AND workers keeping up = shallow standing queue qd_max <= qd_lo) -> tomoGrowFront; BACK (qd_max >= 4*popmax = workers standing >=4 pop-batches behind AND ing_mean <= ing_hi) -> tomoGrowBack. Schmitt bands (hi arms/lo disarms/hold between) + 12-tick sustain + 4*TM_BAL_SETTLE post-flip cooldown. KEY LESSON: back-pressure MUST be QUEUE DEPTH not busy% — busy_max saturates under any heavy load even when workers keep up, causing 4/4<->5/3 FLAPPING; switching to qd (standing backlog) stopped the flap. Requires tomokv-thread-balance on (also feeds busy_ewma_q4 so the grow-front client rebalance runs EWMA-weighted, resolving the earlier busy_target=0 conn-count fallback).
BENCH (memtier read-only d8 P32 front-heavy, 800k keys): static 4/4 7.91M, 5/3 9.18M, 6/2 9.54M; AUTO adapts 4/4->5/3 no-flap = 8.91M (beats base 4/4, near 5/3, short of 6/2). KNOWN TUNING GAP: when workers back up, io threads busy-poll on replies -> aeProcessEventsIO returns ~0 events -> ingress EWMA reads artificially LOW (io WAITING looks like io IDLE) -> masks the front-pressure that would justify the last step to 6/2. Needs a better io-saturation signal (ROB occupancy / accept-queue depth) — retune on real multi-CCD Threadripper per the standing 'DRAM/convergence re-measure on EPYC' rule; do NOT finalize thresholds on the 8-core sim.
STATE: ALL flip mechanisms built + validated on worktree flip-actuator (4 commits d6398e4f2 grow-front-under-load+rebalance, d570f061f grow-back, d817c4672 controller). Knobs: tomokv-flip-rebalance (bool, default on), tomokv-modeshift-test 7=grow-front / 8=grow-back (manual test driver), tomokv-thread-balance (enables auto controller). NEXT: merge worktree -> 2s-numa-dev; then the flip-flop curve bench (flipped==booted vs penalty) + gate suite on numa; controller threshold retune deferred to Threadripper.

*** MERGED TO 2s-numa-dev (2026-07-22): worktree flip-actuator fast-forwarded onto 2s-numa-dev (now at d817c4672, +461 lines over 2f3bc722f). Rebuilt clean in the canonical dir /shared/Projects/THredis-v13-2s (make -j USE_URING=yes). Smoke test on merged binary: manual grow-front x2 -> io6ex2 -> grow-back x2 -> io4ex4, integrity 40k/40k, db conserved, crash=0. NOT pushed to origin (per commit-only-when-asked rule). CAVEAT: don't run the manual modeshift knob (7/8) AND the auto controller (thread-balance) at the same time — they compete for flips and the 'a flip is already in progress' guard makes one refuse (safe, no corruption, but the manual round-trip won't complete). Auto controller is the production path; the knob is the test driver. NEXT (unchanged): flip-flop curve bench (flipped==booted vs migration penalty), full gate suite on numa (xshard/mig/arm/ringwrap/mass_kill), controller threshold retune on Threadripper.

*** EXTREMUM-SEEKING FLIP CONTROLLER (2026-07-22, commit 7fdff12df, PUSHED to origin 2s-numa-dev). User rejected fixed thresholds in stages: "EWMA only WITHIN nodes not between"; "controller like PID — eager flip then if worse flip back + up threshold for stability"; "don't want threshold static, it's pid self tuning"; "should try 6/2"; "mathematically driven, precise, adaptable, smooth"; "nothing set in stone, no static number, all relative, thresholds adjusted by pre/post-flip numbers". FINAL DESIGN = self-calibrating EXTREMUM-SEEKING (gradient ascent on MEASURED node throughput): estimate node ops/s as EWMA mean+variance; probe a flip, judge by z=(rate_after-rate_before)/sigma; z>1 (gain exceeds noise)=keep+climb, else revert. NO absolute pressure/throughput threshold anywhere — sigma (measured noise) is the only scale. ADAPTIVE WARMUP waits for the post-flip reshard rebalance to settle (successive rates within 1 sigma) before judging — THIS is why it now reaches 6/2 (flipped-6/2 needs ~15s for reshardAutoTune to even out the 1:3 bucket imbalance that grow-front's whole-range-dump creates; measuring mid-rebalance read 7.8M and wrongly reverted). CONVERGENCE: both-neighbours-no-gain => lock+HOLD; conv_mean is a SLOW baseline the fast mean is compared to (re-explore only on >3sigma sustained-4-tick shift, never on noise); exponential backoff. Per-node fctl[]; numa_nodes==1 drives global flip. VALIDATED: read-only d8 P32 climbs 4/4->5/3(z=3.4)->6/2(z=4.6), rejects 7/1 & 5/3, CONVERGED 6/2, 16 holds/0 false-shifts, crash=0.
KEY FINDINGS: (a) stat_numcommands is NOT bumped by worker execution in this fork — throughput proxy MUST be sum of exThreads[w].ops_total. (b) grow-front dumps the converting worker's WHOLE range on one neighbor => compounding 1:3 bucket imbalance after 4/4->6/2 => flipped-6/2 caps ~8.9M vs static-6/2 9.54M until reshardAutoTune converges (~15-18s). Even-redistribution-at-flip is a possible future improvement. (c) within-node scoping: reshardAutoTune neighbor pick + tmRebalanceOntoNewIo now filter same-node (tmNodeOfWorker=w/ex_per_node, tmNodeOfIoSlot). (d) per-node flip EXECUTION for numa>=2 still STUBBED (needs per-worker live_as_ex + fan-out updates + concurrent-migration slots). PHILOSOPHY (user, applies to ALL controllers): mathematically driven, no static magic number, everything relative to measured signal+noise, auto-tune + stable + adaptable. IN FLIGHT 2026-07-22: adversarial code-review workflow (wolrmxvxx) + 4-category bench harness ($CLAUDE_JOB_DIR/tmp/flipbench.sh: 2simnode-vs-1, hot-vs-nonhot, xshard, dynamic front-back-front auto-vs-static) both running.

*** FLIP AUTO-KICKS EWMA BALANCER RIGHT AWAY (2026-07-22, commit 23af32d92, PUSHED). User: "I want flip to auto trigger ewma load balance right away." reshardKickAfterFlip() called on every flip completion (tmFlipTick, both grow-front & grow-back): opens a ~12-tick window (server.tm_rebalance_now) where reshardAutoTune BYPASSES its settle+sustain gates (fires on first hot detection, ~1-3s not ~6s+) AND moves 8x-bigger chunks (cap = half hot range, never empties hot shard). Fixes the flip's whole-range-dump imbalance (~1:3 after 4/4->6/2) that used to cap flipped-6/2 at 8.96M-after-18s. RESULT: flipped-6/2 = 9.56M in ~6s == static-6/2 (9.5M). Integrity: full 50k scan under concurrent writes across both flips = 0 misses, db conserved, crash=0. Controller adaptive-warmup now settles faster too. All gates (outlier/adjacency/validation/no-empty) still apply. BENCH SUITE ($CLAUDE_JOB_DIR/tmp/bench_results.txt) done: [4] 2simnode≈1simnode 5.45M uniform (parity, 1 phys node); [2] hot-key≈uniform 5.48M (balancer handles hot); [3] xshard SINTER/ZINTER pipeline on≈off ~3.2ms (huge∩tiny drives from small set both ways — magnitude claim still needs the 2-large-set shape); [1] dynamic AUTO front=9.42M vs static-4/4 7.96M (+18%, climbed to 6/2, 5 flips) — BUT my "back"=write512B workload was io-bound not worker-bound (static-6/2 3.70M > static-2/6 1.66M for writes), so grow-back wasn't exercised; need COMPUTE-heavy (big SINTER/BITCOUNT) for a true worker-bound back phase. Adversarial review workflow wolrmxvxx ran on 7fdff12df (pre-kick).

*** ADVERSARIAL REVIEW wolrmxvxx (2026-07-22, 27 agents, 2.1M tokens, max effort) on the flip diff 2f3bc722f..HEAD. 6 CONFIRMED + 4 PLAUSIBLE. ALL confirmed FIXED + PUSHED (commits a78dd20d5 [7], 5fd0c998d [1-6]): [1] P0 DATA LOSS — cutover fence_acked reset (C.1) cleared only [0,io_threads] but C.2 drain spans nprod=io_threads+tm_ngrow_io => grown producer's stale fence_acked=1 => in-flight range write dropped past FLIP => silent lost write. Reset now spans nprod. [2] growth io slots collided with spare io_slot (both io_threads) => binding overwrite + ctx alias => crash; flip & spare now mutually exclusive (no spare when tm_ngrow_io>0). [3] grow-back IO-EXIT never parked with a pinned non-migratable conn (SUBSCRIBE/BLPOP/MULTI) => tm_flip_ctx stuck => ALL flips frozen. Fixed: pre-check refuses + phase-0 watchdog(~10s) ABORTS via TM_MIGREQ_IOEXIT_CANCEL (re-join accept group, stay IO). [4] freebackDrainAll drained only [0,io_threads] => converted-worker-as-io-producer zerocopy reply decrefs never drained => ring fills => freebackPush spins forever. Widened. [5] grow-back 'neighbour too small' published ZERO-bucket live worker grow-front refused => pool stuck a core short; grow-front now converts zero-bucket directly (park->IO). [6] controller phase-2 revert ignored tmFlipDo return; now retries on refusal. [7] balancer armed migration during flip window (fixed a78dd20d5: reshardAutoTune returns if tm_flip_ctx). DEFERRED (noted): [8] busy_ewma_q4 plain-int cross-thread read (documented-benign control-plane race, established pattern), [9] tmNodeOfIoSlot spare/unknown => fallback-0 node mis-scope (minor), [10] grow-front delists num_workers_live before FLIP => KEYS/SCAN/DBSIZE skip converting worker's keyspace for the ~1s migration window (transient, MATCHES existing spare-deactivation behavior). All fixes validated: round-trip integrity 5/5, no wedge with pinned subscriber, crash=0. LESSON: every [0,io_threads] loop bound in the flip path had to become [0,io_threads+tm_ngrow_io] — audit for more (fence reset + freeback were the two the earlier per-iotid/queue/nq widening MISSED).
