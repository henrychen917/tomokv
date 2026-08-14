---
name: thredis-external-review-fixes
description: "2026-07-20 external (ChatGPT) review of stable: verdicts after adversarial verification + the fix series on 2s-crossshard-dev (2 P0 data-loss, 2 P1 perf, atomics/harness P2)"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

User had ChatGPT 5.6 review origin/stable (tomokv repo); I adversarially verified every finding
(5-agent workflow + first-party repros) per [[thredis-sanity-gate-benching]] — several confirmed,
two MATERIALLY CORRECTED, plus bugs the external review missed. Fix series lands on
2s-crossshard-dev -> stable, then merges into 2s-shared-keyspace-dev.

*** SHIPPED 2026-07-20: stable == 2s-crossshard-dev == 9a37e7ffd (P0s 54d70e926, P1s 011ad4223,
P2s 9a37e7ffd); merged into 2s-shared-keyspace-dev @ 4b0d8b67b (conflict resolved: NB-derived
suffix arm supersedes fork's MIG_HI prefix arm). Battery 7/7 + ASAN clean + perf neutral (pinned
interleaved A/B 5.47/5.46 vs 5.46/5.49M — NOTE the earlier 2.63M pinned reading was environmental
throttle; same binary now reads 5.5M; laptop absolute numbers unreliable, interleave-only). Fork
gates re-verified at 16384 (arm_validation space=16384, mig converged byte-exact). ***
XSHARD-FASTER DESIGN IDEAS (user asked, single-db context; user rejects any-worker-executes-with-
locks): ranked = (1) SEMI-JOIN probe shipping: ship smallest input's members to owners, owners
probe OWN buckets lock-free, return verdicts — kills the measured gather dominance, O(smallest*k)
traffic, new CS_RT_PROBE route; (2) owner-compute: dispatch op to LARGEST input's worker, ship
only small inputs; (3) co-access affinity migration via S1's O(1) handoff (heat-aware co-location
— the deferred direct-move item) makes hot pairs single-worker; (4) O(1) value ownership TRANSFER
for 2-hop moves under shared kvstore (unlink+publish ptr+link, release/acquire — full handoff so
S8 refcount rule preserved; replaces DUMP/RESTORE, O(1) vs O(value)); (5) worker->worker HOP2
SPSC mesh (skip coordinator round-trip); (6) bloom pre-filter for big-cap-big. NOT the abandoned
value-forwarding (that was latency-hiding; these are volume elimination).
VERDICTS + FIXES (commits 54d70e926 P0s, 011ad4223 P1s, 9a37e7ffd P2s):
1. P0 CONFIRMED invalid-src reshard = data loss. reshardArm validated only numeric bounds; engine
   ASSUMES boundary-aligned suffix/prefix of src's contiguous range (its own comment says caller
   validates; none did). Live repro: START over w0-owned range with src=2 accepted, converged=1 on
   0-vs-0 checksums (vacuous!), post-flip key unreachable. EXTRAS the review missed: concurrent
   in-range writer on third worker = SECOND SPSC producer (heap corruption); misaligned arm poisons
   ex_bucket_end => AUTO tuner then arms ownership-violating migrations ITSELF; arm gate was
   load-then-store race (DEBUG on IO thread vs autotune on main). FIX: reshardRangeValid (adjacency,
   containment, non-total, boundary-aligned, per-bucket ownership) + mig_arm_lock atomic exchange +
   acquire on migration_active. NOTE: the old harness arm [0,512) 0->1 (prefix-to-right) was ITSELF
   invalid and silently corrupted ex_bucket_end — all mig harnesses now arm w0's SUFFIX half
   [NB/8,NB/4). Gate: harness/mig/reshard_arm_validation.sh (5 rejects + valid arm + return arm).
2. P0 CONFIRMED migLogPush full-check: masked (t+1) vs RAW monotonic head — matches only while
   head<cap, so after B's first 64K pops backpressure PERMANENTLY DISARMED => lagging B lapped =>
   lost effects (applied_seq skips lost seqs, convergence looks clean!) + double-free in migLogFree.
   FIX: wrap-safe `t - cached_head > cap_mask` (2^32-safe since cap|2^32; reclaims sacrificed slot).
   Rest of ring (SPSC ordering, seqs) verified sound. Gate: harness/mig/mig_ringwrap_test.sh (700k
   keys, 87,733 entries cross the 64K boundary, byte-exact converged).
3. P1 PARTIAL/CORRECTED SINTER/ZINTER driver. ChatGPT r1 said "pick smallest" — WRONG DIRECTION:
   coordinator only has gathered arrays, cost = build-temps(others) + scan(driver); build >> probe
   (zset skiplist ~5x). Their r2 empirics agreed (ZINTER inverted 5.2x). FIX: driver = LARGEST
   (skip its temp build), scan raw sds arrays (kills sdsnewlen churn), empty-input early-exit
   everywhere (incl. csInterCardLimited pre-probe-build). ZINTER score fold DECOUPLED from driver,
   done in STOCK order (cardinality-ascending, tie orig index, NaN->0 first folded) — this FIXED a
   live stock divergence the review missed: old argv-order fold zeroed input 0's NaN so
   `ZINTER 2 big small WEIGHTS 1 inf` = 0 vs stock 5. A/B (interleaved, same seed): zinter bad
   order 2348->425ms (5.5x), good unchanged; sinter both orders 2.2-2.7x faster. DIFF untouched
   (asymmetric, driver must stay input 0 — only its pointless temp build dropped).
4. P1 CONFIRMED-UNDERSTATED fake-ring decay churn: fake_ring_hwm_ewma folded a 1Hz INSTANTANEOUS
   dispatchid-flushid sample = 0 for ANY sub-second-draining client (even saturating P16) =>
   target->1 => cron freed + next burst re-created 15/16 ring every ~3s forever (~45 alloc+45 free
   /client/cycle). FIX: fake_ring_hwm_win true window max updated at dispatch (1 compare on a
   dirty line); cron folds max(win, inflight), resets win. Idle clients still decay (D3 purpose).
5. P2 CONFIRMED atomics class: ops_total, netstat[].in/out, kstat[].hits/misses plain but
   cross-thread (+ RESETSTAT cross-thread zeroing = write/write lost-update race even on x86);
   express_hit_ewma read TWICE in Schmitt gate (could act on 2 values). REFUTED for loop_seq/
   migration block/drain_ewma (already atomic/thread-local). FIX: _Atomic + tomoRelaxedBump/Read/
   Set macros (server.h) — single-writer relaxed load+store = plain mov/add on x86 (NEVER bare +=
   on _Atomic: that's a lock xadd); ewma read once into local; zmalloc->zcalloc initExThreads.
6. P2 CONFIRMED harness gaps: corruption gate verdict ignored empty (missing canary = silent
   data loss would PASS) — now empty>0 fails; mig harnesses hardcoded machine paths — now
   repo-relative + PORT env + mktemp + NB derived from probes (4096/16384 both work).

FOLLOW-UPS: port shared fixes to the 3s/pool fork ([[thredis-canonical-forks-and-dfly-port]] rule)
— the reshard/migLog/atomics code exists there too if v8d-derived. ChatGPT r2 note: SINTER gather
cost dominates (~1.4x only) — the real cross-shard set-op win is not gathering at all (lock-borrow,
S3 of [[thredis-shared-keyspace-fork]]).

Related: [[thredis-xshard-universal]] [[thredis-shared-keyspace-fork]] [[thredis-v8d-migration-validated]]
