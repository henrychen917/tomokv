# Loop 2 journal — forwarding + deep uring
## MERGE LANDED | canonical tips: stable=main=5f6d47221, 3-stage=740fd8bfe, 2s-auto=c86ddfb71,
3s-auto=981c6c41f. ex0 removed (boot-FATAL), MULTI gate always-active. NEW pre-existing find:
--pipe reply undercount <=32 (=ring depth), reproduced pre-merge on b113b836d — end-of-pipeline
reply reorder family; RADAR for loop 2 (forwarding touches the reply path!).

## TRACK U (deep io_uring) — DONE, 3 commits pushed @ d4b06d06a (2s-deep-uring-dev)
Commits: 4315accef (U2 recv), 5c77d7b32 (U1+U3 send redesign), d4b06d06a (README).
- U1: send rings SI|DTR (probe-then-fallback, boot line names mode) + register_ring_fd + the pass's
  single submit is now submit_and_wait(1); hard/partial-submit no-block guards added. Recv arm /
  re-arm / cancel submits stay immediate (cold; batching the cancel would reopen W6-U2).
- U2: tomokv-uring-bufring knob (0=auto 512, pow2 round-up, [64,65536], CQSIZE 2x) + POLL_FIRST on
  multishot arms + ENOBUFS re-arm verified safe-by-construction + log-once. RECV RING STAYS PLAIN:
  6.17 probe = cross-task submit AND REGISTER_SYNC_CANCEL on SI|DTR ring both -EINVAL, and the
  main-thread pause-window disarm cancel (W6-U2 fix) must keep working. Documented in code+boot log.
- U3: ZC sync-notif-wait flaw fixed via DETACH-ON-SUBMIT (entry table owns buf; client gets fresh
  buf at submit => pin-as-ownership-transfer, zero per-op pin checks; notifs reaped async at later
  pass starts, touch entry state only => no cross-pass client UAF possible). Registered sparse pool
  (128x16K/thread lazy): steady-state ZC = SEND_ZC_FIXED. tomokv-uring-zc-min knob (default 1024,
  was hardwired 4096). Kernel probe: eventfd DOES fire under DTR (io_uring_get_events flush needed
  for visibility). GOTCHA for eval: uring-ZC only sees traffic via reply-send routing (v12-J knob)
  or inline big replies — worker replies bypass the ring otherwise; encoded (BULK_STR_REF) replies
  always take the writev fallback (that's the S8 lineage, nothing to pin).
- GATES on 6403: knobsoff/uring/recv/send/zc/ALL combos 0 fails 0 asserts (~4.5-6.7k conn-loops
  each incl 3000B+15000B byte-exact + MGET); ASAN(all knobs) 60s 3-loop mixed + 8423 reconnects +
  2324 CLIENT KILL sweeps = ZERO reports; non-uring build links w/ zero iou* symbols (all gated);
  hot paths untouched knobs-off. Track F ran 437% CPU on cores 0-3 the whole time (contended box —
  smoke hangs early on were starvation, differential-verified, not code).
- EPYC/real-NIC remaining: perf eval (loopback=neutral expected, KEEP bar was correctness), bufring
  sizing via the ENOBUFS log, zc-min sweep vs tomokv-zerocopy-min-value interplay, SQPOLL-vs-SI|DTR
  A/B, pool slot count (128 const now — knob it if EPYC says so), modeshift-under-uring on AUTO fork.

## TRACK F — forwarding reborn (F1 L0 worker read-latch): FAILED pre-registered gate, REVERTED
Branch 2s-forwarding2-dev stays @ 5f6d47221 (tree reverted to pristine, rebuilt+verified sha :0
jemalloc). Full working patch preserved: selfimprove/f1_l0_latch.patch (328 lines, 7 files).

### What was built (F1, complete + correct)
Per-shard-db L0 read-latch: `tomokv-l0-latch` (IMMUTABLE, 0=off no-alloc, N=pow2<=64 boot-FATAL
checked, bench default 8). redisDb gains {l0_latch, l0_mask, l0_epoch(starts 1)}; entries
{hash, version, key sds(dict-owned), kvobj*, expire_at} 40B, zcalloc'd only for ex_dbs.
- Invalidation: db->l0_epoch++ at EVERY write choke point: dbAddInternal, dbAddRDBLoad,
  dbSetValue, dbGenericDelete (unconditional, covers lazy-expire/eviction/migration deletes —
  migApplyOne+migCleanupDeleteRangeA route through dbAdd/dbSyncDelete), setExpireByLink,
  removeExpire (TTL changes; setExpire can REALLOC the kvobj), emptyDbStructure (worker flush
  sentinel calls it), keymeta.c keyMetaSet realloc site. Defrag never touches ex_dbs (verified).
- Probe in lookupKeyReadWithFlags: engages iff db->l0_latch && hash-carry hint armed for this
  exact key ptr (new NON-consuming dictPeekHashHint — dictGetHash's one-shot consume untouched).
  VERSION CHECK FIRST (== l0_epoch proves zero writes since fill => borrowed ptrs live, no UAF
  by construction), then hash, then expire_at vs commandTimeSnapshot() (same clock as
  keyIsExpired; expired-by-cache falls through to dict path so lazy expiry actually deletes),
  then len+memcmp. Hit mirrors lookupKey read bookkeeping (LRU/LFU touch + kstat hits).
  Fill: hits-only, OBJ_STRING-only, epoch read AFTER lookupKey (it may bump via lazy-expire).
- Smoke (6399, io4ex4): set/get/overwrite/del/EX-lapse(nil after TTL)/expire/persist/INCR/APPEND
  after latch-hot reads/FLUSHALL — all correct; latch 0 + 64 boot fine; 5 -> loud FATAL. 15
  bench server runs crash-free (grep REDIS BUG|Guru|signal = 0 in every run).

### Bench (pre-registered matrix, 3 interleaved sanity-gated reps vs base_fwd2, io4ex4 std args,
512B x 8M primed, t8c25 P16 20s; e: 2M x 32B t10c20 P32 — medians base->cand, cand latch=8)
- (a) extreme-hot G stddev=100  [EXPECT WIN]: 2557366 -> 2551776  [-0.22%]  << gate was >= +2%
- (b) medium G stddev=10K       [maybe]     : 2527078 -> 2508250  [-0.75%]
- (c) standard-hot G stddev=400K [neutral]  : 2529543 -> 2515182  [-0.57%]  as expected
- (d) uniform 512B 1:9          [GUARD]     : 2519145 -> 2516420  [-0.11%]  clean (>-1%)
- (e) GET32 2M uniform P32      [GUARD]     : 7925174 -> 7873105  [-0.66%]  clean (>-1%)
Attribution ablation (SAME cand binary, quiet box, latch 0 vs 64, 3 reps):
- (a) s=100:  0=2540171  64=2555641 [+0.61%, 3/3 reps positive — mechanism real but microscopic]
- (a10) s=10 diagnostic (hot set ~40 keys, 64 slots => near-ideal hit rate): 0=2519500
  64=2518752 [-0.03%] — FLAT AT NEAR-100%-COVERAGE.
Cross-checks: ablation latch-0 (a) within 0.7% of matrix BASE (a) => matrix not polluted by the
brief track-U overlap; all cells sanity-gated (floors + crash=0), zero discards in the clean run.

### Verdict + physics (why this fails everywhere here)
512B P16 GET cells sit at the same ~2.52-2.56M ops/s ceiling REGARDLESS of skew (a≈b≈c≈d on
base!) — the regime is send/dispatch-bound, the shard-dict walk is NOT on the critical path; and
in skewed workloads the hot keys' dict lines are cache-resident anyway (hot => warm — the latch's
target is self-negating on a single socket). Even a ~near-100%-hit latch (a10@64) moves nothing.
This independently reproduces the value-forwarding dead-end conclusion from the OTHER direction:
predictor-forwarding failed on run-length 1.008; the latch removes the same non-bottleneck with
zero prediction and still buys nothing on this box. F1 fails its own pre-registered keep rule =>
REVERTED (no commit), per knob-collapse doctrine (no dead knobs).
- F2 (batch-local same-key coalescing) SKIPPED on evidence, not time: it elides a strict SUBSET
  of the lookups the latch already elided (same-batch dupes ARE latch hits — fill by first, hit
  by rest, epoch unchanged), and eliding ~90% of hot lookups measured 0. Physics-excluded here.
- ASAN churn moot (no keep); churn script ready at scratchpad f1/churn.sh if ever revived.
- Threadripper revival note (F3-flavored, doc-only): the latch becomes interesting ONLY when a
  warm lookup is still expensive => cross-CCD/NUMA remote-L3/DRAM shard access on 9965WX, where
  worker-local latch hits remove interconnect traffic. The patch is correctness-complete and
  gated; re-apply f1_l0_latch.patch there and rerun THIS matrix + a10 ablation as the decision
  gate (win must clear +2% at (a) with (d)/(e) guards clean).

### Harness gotcha (cost ~45min, now fixed in my scripts)
`fuser -k PORT/tcp` prints killed PIDs to STDOUT (no trailing newline) — inside `$(one ...)`
captures it glues a PID onto the first metric token and shifts every field (first matrix run
produced monotonically-growing garbage = PIDs; all reps DISCARDed by the sanity gates, which is
exactly what they are for). Rule: `fuser -k ... >/dev/null 2>&1` ALWAYS; and pre-flight one
dry-run rep of any new one()-style harness before burning real reps (added to my checklist).
## TRACKS LANDED | ~2026-07-06 08:30 UTC
F1 L0 LATCH: implemented fully+correctly, FAILED pre-registered gate (extreme-hot -0.22% vs >=+2%),
REVERTED. Patch preserved (f1_l0_latch.patch). THIRD PHYSICS WALL (doctrine-grade): hot keys have
hot dict paths — latch-hittable keys are L1-resident in the dict already; expensive (cold/DRAM)
lookups never repeat. Forwarding-as-cache cannot beat the hardware caching the table itself.
U TRACK: COMPLETE, 3 commits pushed (d4b06d06a tip): SI|DTR probe+fallback per-thread (6.17 quirks
documented: recv ring stays plain to keep W6-U2 cancel fix), register_ring_fd, submit_and_wait
batching, bufring knob+POLL_FIRST+ENOBUFS-verified, ZC DETACH-ON-SUBMIT (ownership transfer — UAF
impossible by construction, F_NOTIF reaped async). EPYC-ready, all knobs default-off.
NEXT: F2 cheap falsification (prior now LOW — same wall predicted), --pipe undercount investigation,
U epoll non-regression insurance bench.
## STAGE 2 LANDED + STAGE 3 LAUNCHED | ~2026-07-06 09:30 UTC
HEADLINE (task B): --pipe undercount = REAL RESP ORDERING VIOLATION, fully mechanized: inline-fake
cmds (PING/ECHO family) never set the dispatched-fake exemption -> _prepareClientToWrite enqueues
the FAKE into clients_pending_write -> handleClientsWithPendingWrites writes its reply DIRECTLY to
the shared conn AHEAD of <=31 older in-flight ring replies (drain-splice blocks at first incomplete
slot — that path is order-correct). Wire probe: zero loss, pure reorder, sentinel 2-29 early, 4/20
runs. Affects ANY pipelining client mixing PING with data cmds. Pre-existing (canonical b113b836d).
Fix = make inline fake exempt (reply rides ordered drain only) — stage 3 implementing + validating
(20-run repro to 0/20, wire-order probe, perf guards incl PING-heavy cell).
A-track orphaned (premature-return again): F2 partial preserved (f2_coalesce_partial.patch 221
lines), tree reverted; F2 bench + U epoll insurance re-queued serially in stage 3.
## DFLY URING STUDY DONE | 2026-07-07 ~06:00 UTC
Dragonfly/helio uring: SI|DTR|COOP|TASKRUN_FLAG|SUBMIT_ALL (kernel-gated, LOG(FATAL) no fallback);
batched submit_and_get_events once/pass + SQ_TASKRUN skip-the-enter; register_ring_fd; MSG_RING
cross-thread wake (on own ring); DEFAULT SYNC recv (multishot+bufring OPT-IN, off by default);
**PLAIN SEND/SENDMSG — NO zero-copy send anywhere** (grep-confirmed); no multishot accept;
SO_INCOMING_CPU steering; migrate-socket-to-owner so cancels same-thread (sidesteps our -EINVAL).
vs US: we match/exceed setup (fallback+CQSIZE), match submit-once/pass + multishot-recv+POLL_FIRST,
GO BEYOND on send (ZC+regbufs = what helio leaves unexploited). Adoptable gaps: RECVSEND_BUNDLE +
incremental bufs (recv), SO_INCOMING_CPU/NAPI steer, SQ_TASKRUN skip-enter, SUBMIT_ALL/TASKRUN_FLAG.
GET COLLAPSE ROOT CAUSE (2 layers): (A) FUNDAMENTAL compile cap reply_builder.h kMaxBufferSize=8192
+ kMaxInlineSize=32 -> >32B values go as external iovec, flush every ~8 replies (~4KB) vs coalesce
~128 at 32B => ~16x more SENDMSG; (B) TUNABLE default --pipeline_squash=1 capture/replay+borrow-pin
(negligible 32B, dominant 512B). FIX: --pipeline_squash=0 or --squashed_reply_size_limit=N (runtime);
cap itself needs recompile. Ties to us: our ZC/detached-send keeps large value as ONE DMA (no
fragment) -> real-NIC large-value = our design should pull ahead. FLAG-SWEEP queued to confirm.
## 2x2 URING HEAD-TO-HEAD DONE | 2026-07-07 ~05:28 UTC (medians M ops/s, 3 tight rounds)
             GET32  MIX32  GET512  GET4k
dur_uring    7.567  6.689  2.499   1.195
dur_epoll    7.996  6.971  2.580   1.272   <- our epoll SLIGHTLY beats our uring (loopback: uring
dfly_uring   5.771  5.453  0.823   0.608      overhead unrecovered — EXACTLY the "naive uring
dfly_epoll   5.464  5.104  1.029   0.772      net-neutral on loopback" prediction; payoff=real-NIC)
FINDINGS: (1) io_uring on loopback = neutral-to-slightly-NEGATIVE for BOTH engines (our uring -5%
GET32 vs our epoll; dfly uring WORSE than dfly epoll on large values 0.82 vs 1.03 GET512). Confirms
VLDB naive-uring guidance; our uring value is EPYC/real-NIC (ZC-send). (2) COLLAPSE reproduces hard:
dfly GET512 0.82M vs ours 2.58M = 3.1x; and dfly's OWN uring makes it worse (fragmentation x SQE
overhead). (3) WE BEAT DRAGONFLY ON EVERY CELL: GET32 1.38x, MIX32 1.28x, GET512 2.5x, GET4k 1.65x
(vs dfly's best engine per cell). All numbers reproduce historical master-sweep values.
## COLLAPSE FLAG-SWEEP | 2026-07-07 ~05:34 — SANITY-GATE OVERTURNED THE SOURCE HYPOTHESIS
Predicted (source): --pipeline_squash=0 recovers, --force_epoll no-op. MEASURED: squash=0 = NO change
(0.844 vs 0.838; borrowed-GET path already near-zero-copy); --force_epoll = +23% (1.03 vs 0.84 GET512).
=> collapse dominated by Mechanism A (compile-time 8KB cap): its fragmented SENDMSGs cost MORE via
io_uring (SQE+CQE/fragment) than epoll writev. NOT config-fixable: best flag still 2.5x below us
(1.03 vs 2.58), real cap needs recompile => STRUCTURAL. Doctrine reaffirmed: bench every claim incl
source-derived ones. REPORT.md C.1 filled + corrected.
