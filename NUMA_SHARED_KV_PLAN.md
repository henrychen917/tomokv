# NUMA shared-keyspace: implementation plan (fork `2s-numa-shared-kv-dev`)

## Why this fork exists (the correction)

Prior belief: "each node shares 1 db, which is why EWMA reshards are cheap." **Not true in the
code.** The NUMA branch is built directly on top of `2s-shared-keyspace-dev`, which only ever
shipped **S0.1** (`TOMO_BUCKETS` 4096→16384, commit `6060c4d67`). The two stages that actually
create the shared db and the cheap reshard were **designed but never implemented**:

- **S0.2** — collapse the per-worker 1-dict kvstores (`ex_dbs[w][j]`, `slot_count_bits=0`) into one
  shared 16384-dict kvstore per db.
- **S1** — delete the copy engine; a reshard becomes an O(1) `ex_bucket_table[b]` flip.

Proof it's unbuilt: `migApplyOne` (server.c:9008) still does `rdbLoadObject` + `dbAdd(bdb,…)` —
reshards **physically copy every key** between isolated per-worker kvstores. So today a bucket move
is O(keys-in-range), not O(1); the "shared db" does not exist.

This fork implements S0.2 + S1 (following `SHARED_KEYSPACE_DESIGN.md`), so within-node EWMA reshards
become ownership flips and cross-shard within a node collapses toward local work.

## Target model (user-refined 2026-07-22: db-per-NODE, not one global)

- **One physical `kvstore` per NODE per logical db** (`node_dbs[node][dbid]`; e.g. 4 nodes × 4
  cores = 4 physical dbs). Every worker of a node points at its node's db
  (`exThreads[w].db = node_dbs[tmNodeOfWorker(w)]`). `num_dicts_bits = 14` (16384 bucket-dicts;
  the cluster-path configuration kvstore already supports); a node's kvstore only ever populates
  its own contiguous bucket range — dict index stays the GLOBAL bucket id, so `getKeySlot` is
  uniform and no per-node re-basing exists.
- **dict index = ownership bucket = `xxh64(key) & 16383`** — the SAME value `ex_bucket_table` keys
  on. `owner(bucket)` is the exclusive toucher of `dict[bucket]` ("virtual buckets": a node's
  workers own disjoint slices of the shared node db). The single-writer invariant shrinks from
  "a whole worker-db" to "a bucket-dict" — **no sync on the hot path**; only M-commands ever touch
  another worker's slice, under the per-worker lock ("we still lock every time, but we never
  contend" — the uncontended-CAS discipline from MCMD_LOCK_DESIGN.md).
- **NUMA locality is structural**: the whole node kvstore (dict array, aggregates, bucket-dicts)
  belongs to one node — first-touch by node-local workers places it in node memory. No cross-node
  shared cache lines at all (a single global kvstore would share its dict-pointer array + aggregate
  lines across nodes).
- **Reshard = drain + flip.** Cross-node balancing is disabled by design, so EVERY reshard (EWMA
  move or flip grow-front/back bucket handoff) is within one node = within one kvstore: drain A's
  in-flight ops on `b` (reuse `migHoldIfDraining`), release-fence, `ex_bucket_table[b] = B`, hand
  off partitioned aggregates. No dict move, no key copy — the copy engine dies entirely.

## The one real cost — shared kvstore aggregate state (must partition)

`cumulativeKeyCountAdd` (kvstore.c:83) mutates `key_count`, `non_empty_dicts`, and the Fenwick
`dict_sizes` on every add/delete. Shared across worker threads → race. Resolution:

- **Per-worker partitioned counters** (`key_count`/`bucket_count`/`non_empty` over that worker's
  OWNED buckets); global = sum-on-demand (DBSIZE already sums across workers, db.c:2184).
- **Fenwick `dict_sizes` → lazy / per-worker.** Only SCAN + size-weighted RANDOMKEY read it (S2
  work), not the add/delete hot path.
- **No shared atomics on add/delete.** Hot path touches only the owned bucket-dict + this worker's
  private counters.

## Staged plan — each stage byte-exact vs the previous, gated by `harness/xshard_corruption.sh`

| Stage | Change | Gate |
|-------|--------|------|
| **S0.2a** | Dict-selection routes by `xxh64(key)&16383` (a worker fake carries its bucket in `->slot`; `getKeySlot` returns it). Keep per-worker kvstores but move them to `num_dicts_bits=14`; a worker only ever touches its owned bucket-dicts. Per-worker aggregates unchanged (still isolated → no race yet). | boot + `xshard_corruption` + smoke MGET/SET byte-exact |
| **S0.2b** | Collapse the per-worker kvstores into ONE kvstore per NODE per db (`node_dbs[node][dbid]`, all node workers share it); kvstore global stats (key_count/non_empty/Fenwick) skipped via flag, per-WORKER key counts kept server-side (owner-only writes, no atomics; owner = `ex_bucket_table[slot]`, available at every dbAdd/delete since slot==bucket); DBSIZE/RANDOMKEY read the per-worker counts. Ownership static 1:1 with today. | byte-exact + perf-neutral; ASAN clean under churn |
| **S0.2c** | Point `expires` (+ subexpires) kvstores at the shared model; fix DBSIZE/KEYS/RANDOMKEY/FLUSH cross-worker code (mostly simplifies). SCAN left on its decoy (pre-existing). | byte-exact; `validate_all.sh` |
| **S1** | Delete `migApplyOne`/`migScanA`/`migCleanupDeleteRangeA` copy engine; reshard = drain-fence + `ex_bucket_table[b]` flip + partitioned-aggregate handoff. | migration correctness under live reshard (mig harness) + measured EWMA cost drop vs copy engine |
| **S1.5** | First-touch NUMA placement of bucket-dicts (node-local memory). | perf on real NUMA (deferred to hardware) |

Then the cross-shard payoff (the original ask): with the shared kvstore, a multi-key command whose
keys are all one worker's/one node's buckets runs the **stock proc** directly (already the
`xshard_localfast` path — it just gets much wider), and the per-node borrow reads become a plain
shared-kvstore access under the bucket owner. That work rides on top of S0.2+S1; do it after S1
lands.

## Invariants (every stage)

1. A bucket-dict is touched by exactly one worker between fences (single-writer preserved).
2. The add/delete hot path touches no cross-worker shared cache line.
3. `bucket = xxh64(key) & (TOMO_BUCKETS-1)` is stable; only `ex_bucket_table` changes on reshard.
4. Byte-exact vs the previous stage (`harness/xshard_corruption.sh`).

## Status

- Forked `2s-numa-shared-kv-dev` off the NUMA branch (has S0.1 + the flip/mcmd-lock work).
- **S0.2a DONE + gated** (commit 1ecf550f7): dict index == bucket, 16384-dict kvstores, per-worker
  isolation kept. Corruption+intercard PASS, 6 live copy-reshards clean, perf 0.98x (wash).
- **S0.2b + S1 DONE + gated** (this commit): per-NODE physical dbs (ex_dbs[w] aliases
  node_dbs[w/wpn]), KVSTORE_SHARED_MT (atomic aggregates, Fenwick skipped +
  linear-scan fallbacks, rehash-list spinlock, release-published dict creation), per-node FLUSH
  rendezvous barrier, worker-range RANDOMKEY, node-summed DBSIZE, per-worker-range KEYS subs, and
  **reshard = drain-fence + O(1) ownership flip** (no scan, no log, no cleanup; cross-node
  arms rejected — same-physical-db required). Gate: smoke all-green (DBSIZE/KEYS exact, RANDOMKEY,
  TTL, FLUSHALL-under-load), 10 flips under 951k concurrent borrow+write ops => 0 integrity errors
  (issued=applied=0 — nothing copied), corruption harness PASS at MAX sharing (numa=1: 4 workers on
  ONE kvstore), intercard PASS, perf A/B vs S0.2a: GET 1.02x / SET 1.05x (neutral).
- **Wedge found during gating = PRE-EXISTING, not S0.2b**: flips + mass connection-kill + FLUSHALL
  livelocks the server (all threads R). Bisected: reproduces IDENTICALLY on the S0.2a parent (and
  matches the documented freeClientsInAsyncFreeQueue mass-hard-kill livelock that repros on legacy).
  Deterministic recipe: 10 DEBUG-RESHARD flips under load, then kill 16 bench conns, then FLUSHALL.
  The flush barrier itself traced clean (4 arrivals / 2 empties per flush). TODO: root-cause the
  legacy livelock separately.
- KNOWN GAPS: estore (HFE) aggregates not MT-safe on shared dbs; S2 keyspace-wide ops
  (SCAN on shards) unchanged. (The old "SPARE activation into a shared node is rejected" gap went
  away with the reserve thread, deleted 2026-07-28.)
- NEXT: S1.5 first-touch NUMA placement (needs real hardware); then the cross-shard payoff — run
  within-node multi-key commands as stock procs on the node kvstore (widened xshard_localfast) and
  simplify the per-node borrow to a shared-kvstore access.

## Bench matrix (2026-07-22, post park-fix 5a7b2326c; single-CCD sim, server 0-7 / loadgen 8-15)
Configs: n2 = 2 simnodes (2io+2ex/node), n1 = 1 simnode (4io+4ex); flip = thread-modes+balance;
all with mcmd-lock on. Mean of 2 interleaved rounds, ~±15% box drift. MIX = 4 op types concurrent
(sum of stream rates). 0 crashes in all 28 runs; n1-flip controller reached 6io/2ex BOTH rounds.

test     n2-static  n2-flip  n1-static  n1-flip | n2flip/st n1flip/st n2st/n1st
SET         1314k    1412k      1431k     1446k |   1.07      1.01      0.92
GET         1531k    1506k      1598k     1465k |   0.98      0.92      0.96
MGET8        537k     576k       697k      692k |   1.07      0.99      0.77
MSET8        682k     642k       616k      672k |   0.94      1.09      1.11
MIX         3456k    3441k      3558k     3602k |   1.00      1.01      0.97
SEThot      1617k    1543k      1612k     1594k |   0.95      0.99      1.00
GEThot      1569k    1715k      1524k     1620k |   1.09      1.06      1.03

VERDICTS: (1) flip-vs-static is a WASH on this box (within drift) except GEThot (+6-9%, positive in
4/4 rounds — the only consistent flip win) and n1 GET (0.92x both rounds — mid-bench probe churn +
6/2 not clearly optimal for uniform GET on the 2s fork; needs a settled-state re-measure). n2 flip ==
static as expected (actuators staged). (2) n2-vs-n1: MGET8 0.77x re-confirms the per-node-split cost
at small N on one CCD (matches the earlier 0.73-0.86x sweep); MSET8 1.11x — n2 FASTER on multi-key
writes: TWO kvstores halve the write-path aggregate-atomic contention (per-node dbs pay on writes
even without NUMA); GET/SET show a mild ~4-8% n2 tax. All single-CCD; real-NUMA re-measure pending.

## Per-node flip + controller-inputs fix (2026-07-22 late)
- **Per-node actuators LIVE** (was staged): per-node live prefixes (tm_node_wlive) + tmWorkerLive
  predicate; all global-prefix consumers converted (RANDOMKEY weight, KEYS fan, autotuner fold/var/
  neighbor, DEBUG bounds, FLUSH scan). Same algorithm as a big node at any wpn>=2: convert the
  node's highest live worker. Test hook: modeshift-test 70+n/80+n. Validated: both nodes
  independently 2/2->3/1 and back, under load (667k ops 0 errors), non-prefix live set exact
  (KEYS/DBSIZE/RANDOMKEY/MGET). Node flips serialize through the single migration gate (decisions
  independent; concurrent migrations = future).
- **MGET/EXISTS stock-vs-borrow A/B** (tomokv-mcmd-nodelocal): stock node-locked MGET = 0.81-0.93x
  of the borrow => borrow stays (group machinery dominates at small N; EXISTS parity proves it).
  SUPERSEDED 2026-07-27: the borrow AND this knob were deleted by owner ruling — the win did not
  justify a non-owner read whose atomicity applied only to non-pipelining clients. See
  README-NUMA.md; multi-key reads are now uniformly owner-only.
- **Controller inputs FIXED**: idle ticks were folded into the EWMA variance => sigma 2x mean =>
  z-gates were noise (controller climbed on garbage). Fix: idle ticks (inst==0 && qd==0 && ing==0)
  freeze mean/var; probing requires offered pressure; priming waits for the first NONZERO rate
  (inst gated on ops_prev_ms baseline, NOT primed — chicken-and-egg fixed). Result: sigma 0.5-1%
  of mean (was 200%), monotone-gain climb 1.39M->1.74M GET reaching 7io/1ex — and settled-flip GET
  (1.74M) BEATS static 4/4 (~1.6M), resolving the matrix's 0.92x mid-climb artifact. numa=2: both
  node controllers probe independently.
- REMAINING controller agenda (the "explore flip algorithms" study): convergence-LOCK not engaging
  (keeps probe-reverting at the optimum = churn), seed-burst overreaction (8 flips during a 3s
  seed), probe-cost accounting (each probe is a real flip), alternatives to evaluate: windowed
  median instead of EWMA, paired-probe with settle-discard, UCB-style exploration budgets.

## Any-core pool + fixes (2026-07-22 night)
- **Any core = worker or io** (>=1 io + >=1 ex per node): delivered by POOL BOOT — 1io+(cpn-1)ex
  per node; every non-base core flips both ways via the per-node actuators; the guards ARE the
  constraint (grow-front refuses at 1 ex/node, grow-back refuses at the base 1 io/node). Validated
  numa=2 cpn=4: each node independently 1/3->2/2->3/1 and back, guards refusing at both edges,
  loads clean, 0 crashes. The one pinned core per node (base io; main on node0) is exactly the
  required min-io.
- **CRITICAL pre-existing fix: non-power-of-2 worker counts were entirely broken** — ex_bucket_end
  used floor((i+1)B/W) while ex_bucket_table used floor(bW/B); the boundary bucket disagreed unless
  W | 16384, so reshardRangeValid's ownership walk rejected EVERY arm (no flips, no balancer moves)
  on 3/6/12-worker configs. All prior validation used powers of 2 and never saw it. Fix: end[i] =
  ceil((i+1)B/W) (exact table boundary; identical for pow2).
- **DEBUG RESHARD PERWORKER protocol desync fixed** (arraylen and loop bound must be the same
  expression -> CLI hang when they diverged).
- **Flip direction chooser (user design)**: first-probe direction = io-vs-ex throughput comparison.
  At steady state the two rates are equal, so their difference IS the queue-depth trend: standing
  worker queues => ex lags => grow back; dry queues => io-bound => grow front. Unit-free, no
  thresholds; gradient still corrects wrong guesses. Validated: GET load logs "first-probe
  dir=FRONT (qd_max=0)" and monotone-climbs to 7io/1ex @1.73M.
- TEST GOTCHA (cost a false-positive round): CONFIG SET with an UNCHANGED value skips the apply
  callback (returns OK, no-op) — modeshift-test must toggle through 0 between repeats.

## Full regression vs original physical shards (2026-07-22 night, post ac5738bb9)
- Harness battery on HEAD: xshard_corruption PASS (0/200 corrupt), xshard_intercard PASS,
  setop_oracle PASS=30 FAIL=0.
- BYTE-EXACT battery vs original build: **108/108 identical** — strings/INCR/expire-family/hash/
  list/set/zset/bitops/HLL single-key + full cross-shard surface (MGET/MSET/DEL/UNLINK/EXISTS/
  TOUCH/KEYS/SINTER/SUNION/SDIFF/SINTERCARD/ZINTER/ZUNION/ZDIFF/ZINTERCARD/*STORE x5/RENAME/
  RENAMENX/COPY/SMOVE/LMOVE/RPOPLPUSH/MSETNX/LMPOP/ZMPOP/PFCOUNT/PFMERGE/BITOP) incl. WRONGTYPE
  and miss cases.
- PERF per family (best-of-2 interleaved, numa=2 io2ex2/node): geomean HEAD/original = **0.997**.
  set 0.97 get 0.94* incr 0.96 lpush 0.90* sadd 0.99 hset 1.01 zadd 1.06 spop 1.00 | mget8 0.95
  mset8 0.96 exists8 1.04 del8 0.96 sinter 1.04 **sintercard 1.22** (node-local payoff).
  *drift-checked +3 rounds: get 1.07/1.04/0.95 (pure noise), lpush 0.88/0.95/0.98 (converges to
  parity; original self-drifts ±9%; possible <=5% residual within noise — re-measure on EPYC/TR).
VERDICT: no regression outside the box's drift envelope for single-key OR cross-shard; one
measured win (SINTERCARD +22%); everything byte-exact.

## Hash-carry + the "consistent tilt" investigation (2026-07-22 late night)
User observed campaign-1 family ratios tilted below 1.0 (8/14 cells). Mechanistic audit found REAL
uniform costs: getKeySlot computes xxh64 per db access (writes pay 2-3x: lookupKeyWrite + dbAdd +
expires) + write-path aggregate atomics + tiny-dict locality at 30k keys (~6 keys/dict).
FIX (hash-carry): dispatch computes argv[1]'s bucket ONCE and stamps it on the fake
(tomo_bkt_ptr/tomo_bkt); getKeySlot consumes on POINTER match via current_client (safe for
multi-key procs — only the exact carried sds hits); borrow loop re-arms per key; hint cleared at
exec end (ring fakes recycle without re-init — a stale ptr could collide with a recycled sds on the
stamp-skipping inline path => wrong bucket; the clear closes it). Gate: 108/108 byte-exact battery
+ 2.34M churn ops 0 errors.
RESULT (best-of-3 interleaved): set 1.00 get 1.04 incr 1.00 lpush 1.05 mget8 1.06 mset8 1.10
del8 1.09 — every campaign-1 negative cell flipped positive — BUT sadd 0.93 hset 0.92 zadd 0.89
flipped negative. EVERY family has now been observed on both sides of parity across campaigns =>
the per-cell sign is CAMPAIGN DRIFT, not a stable regression. Geomeans: 0.997 (pre-carry) ->
1.006 (post-carry) — consistent with a small real gain from removing 1-2 hashes/op. 3M-key check:
GET 0.955 / SET 1.060 (wash; no large-DB tiny-dict penalty). DEFINITIVE settle needs the low-noise
EPYC/TR box (this box shows +/-10% per-family campaign swings).

## Adversarial review round (wf_021200d6, 2026-07-23) — 15 confirmed root causes, 14 fixed
Fixed: [0] concurrent-flush cross-barrier deadlock + [1] main-thread flush-vs-migration deadlock +
[2] flush-vs-flip TOCTOU => ONE tomo_flush_gate (serializes flushes; waiting flushers pump the
coordinator/tick when on main; reshardArm refuses while held; last barrier participant releases).
[3] HFE estore races => node-locked exec under mcmd-lock, honest error without. [4] tempDb 0-bit
kvstore OOB on replica swapdb => tomo 14-bit bits. [5] RANDOMKEY expire-delete unlocked => own-worker
lock. [6] RANDOMKEY node-size weighting (nil on non-empty) => bucket-range-width weights. [7] keysize
histogram races => disabled on shared dbs. [8] hash-carry hint read on uninitialized real clients =>
CLIENT_EX_PENDING guard. [9] SHARDNUMSUB wrong slot => 0 in non-cluster. [10] global grow hooks
corrupt per-node prefixes => refuse on multi-node. [11] [16] node arrays vs numa-nodes<=64 => config
capped 16. [13] straggler sub lands on just-parked worker => converted workers keep draining their
EX queues in IO mode. [14] balancer cron legacy prefix walk => tmWorkerLive predicate.
NOT fixed (accepted): [12] flush stop-the-node duration (semantics documented in README-NUMA §5).
Validation of fixes: 15 concurrent FLUSHALLs + flush-vs-flip hammering => no deadlock, PONG;
HEXPIRE/HTTL work node-locked; SHARDNUMSUB counts; RANDOMKEY 30/30 non-nil at asymmetric flip state;
battery 108/108; corruption harness PASS; 60s stress 1.83M ops / 27 conversions / 0 errors / 0
crashes; perf geomean 0.991 vs original (campaigns: 0.997/1.006/0.991 — parity within drift; incr
1.01/hset 1.00 vs set 0.91/get 0.93 same-path split proves drift not cost).

## Optimization loop (2026-07-23, ~2h): instruction-metered, 3 keepers
METHOD: perf-stat instructions at fixed n, idle-corrected (work = instr - 12.7B/s x wall) — ~1-3%
repeatable vs the box's ±10% rps drift; every keeper has an internal control (untouched paths flat).
- C1's former storage-hash pass reused the dispatch-carried bucket: WASH (~40 of 5100 instr/op)
  — kept as cleanup at the time.
- C2 stackified the M-dispatch scratch (6 heap pairs in tomoMPerNodeDispatch, 5 in
  csBuildCoalescedSubs; [16]/[TOMO_EX_THREADS_MAX+1] stack frames, >128-key heap fallback):
  exists8 -7.1%, mset8 -4.2%, mget8 -2.6% work/op (numa=2 cross-node paths).
- C3 single-pass MGET borrow (append to the reply buffer under each owner lock, key order; replaces
  trylock-backlog + dupStringObject + serialize + free): numa=1 mget8 -13.8% work/op
  (20026->17256 instr); get/exists8 controls ±0.4%. CORRECTION: loopback rps is a WASH (interleaved
  x3: pre 680-701k vs post 614-702k) — the path is not instruction-bound at this operating point on
  this box (savings deepen worker idle-spin); the work/op reduction pays off only where workers are
  the bottleneck (worker-heavy splits, higher load, real NUMA). The commit message's "+15% rps"
  claim was WRONG (an unverified assumption that slipped past the sanity gate) — this note is the
  authoritative record.
VALIDATION: battery 108/108 at numa=1 AND numa=2; 1.26M MGET-heavy churn ops 0 errors.
Not pursued (documented): csGroup/slot monoblock alloc (teardown ownership shared with the
coalesced path — fiddly), inline sub argv (S8 argv-ownership contract risk), knob sweeps (rps-noisy).

## RPS campaign (2026-07-23): 5 interleaved rounds x 3 builds x 2 topologies, median-of-5
Per-cell spreads 8-25% across rounds (the box's drift); medians reduce to ~±3-5% resolution.
head/preopt (the optimization loop's end-to-end effect): numa=1 geomean 1.005 (mget8 1.07 — the C3
target cell), numa=2 geomean 1.011 (mget8 1.03, mset8 1.03, exists8 1.02, sinter 1.04 — every
C2-targeted cell slightly positive). VERDICT: the loop's instruction wins DO surface in medians as
+2-7% on the targeted M-command cells (cross-node paths are partially instruction-bound), ~+1%
overall — small, real, in the right places; earlier "wash" was a 3-sample view.
head/orig (shared vs physical shards): numa=1 geomean 1.036 (sinter 1.15, get 1.06), numa=2 0.986
(set 0.95, exists8 0.94, mset8 1.06). Sixth campaign: 0.986/0.997/1.006/0.991/1.036/0.986 —
PARITY within this box's measurement ability, oscillating around 1.0.
Validation on optimized HEAD: corruption harness PASS (0/200), battery 108/108 both topologies,
1.26M-op churn clean (from the opt-loop gate).

## GET/SET numa=2 "deficit" investigation (2026-07-23)
The 5-round campaign showed numa=2 head/orig get 0.97 / set 0.95 — flagged for investigation since
GET/SET are the headline. Microarch probe (3 interleaved rounds each, perf counters on the server
during fixed-n runs; counters repeatable 1-3% vs rps's 8-20% spreads):
  GET: instr/op -0.9%, cycles/op +1.6%, L1d-miss/op -2.2%, rps -1.5% (rounds fully interleaved)
  SET: instr/op -2.3%, cycles/op -2.2%, L1d-miss/op -3.1%, rps +1.9%
VERDICT: NO structural GET/SET deficit — head does equal-or-LESS work per op with equal-or-fewer
cache misses than the physical-shard build at numa=2 (SET is measurably cheaper). The campaign's
0.97/0.95 cells were drift (SET flipped to +1.9% in this probe; GET's rounds scatter 1.40-1.62M on
both builds). The asymmetry that motivated suspicion (head ahead at numa=1, behind at numa=2) is
itself the drift fingerprint: a real shared-kvstore cost would hit numa=1 HARDER (4-way sharing vs
2-way). Residual: GET cycles/op +1.6% — below this box's actionable threshold; recheck on EPYC/TR.

## numa=1 head-vs-preopt GET/SET cells (2026-07-23, user flag) — investigated, refuted; C1 retired
Campaign cells said numa=1 head/pre get 0.95 / set 0.97. Direct interleaved counter probes:
- Probe A (head+C1 vs preopt): SET clearly BETTER (-5% instr, -14.6% L1d, +4.9% rps); GET slightly
  worse (+2.9% instr, +6.4% L1d, -1.9% rps) — suspected C1's hash-hint read.
- Probe B (three-way with C1 reverted, fresh preopt interleave): the SAME preopt binary measured
  +6.6% more instr/op than in probe A => EVEN COUNTERS drift ±6% ACROSS campaigns (only
  same-campaign interleaved comparisons are trustworthy). -C1 improved GET ~2% but WORSENED SET ~7%
  vs +C1 — code-alignment lottery swings individual paths ±5-7% on any rebuild.
- What survives: in probe B's fresh interleave, head BEAT preopt on both (GET +6.6% rps, SET +0.9%).
  The campaign's 0.95/0.97 do not reproduce under direct comparison => drift.
DECISION: C1 retired (revert kept) — its designed benefit was ~40 instr behind a compare, unmeasurable
at this box's floor; when a change can't be measured, less code wins. The hash-carry proper (getKeySlot
consuming the dispatch bucket — 2-3 hashes per write) is untouched and remains.
METHODOLOGY RULE (add to the box's lore): cross-campaign comparisons are invalid even for hardware
counters; conclusions require same-campaign interleaving, and ±5% path-level swings can be pure
code-layout lottery. Anything finer than that needs the EPYC/TR box.

## 2026-07-23 — flip-controller convergence + abort fixes (sweep tripwire findings)
10h competitive sweep's early tripwire (tomo p32 get −35% / set −69% vs preflight, 70 flips/family)
exposed three controller defects; all fixed + validated before sweep relaunch:
1. **Convergence lock never engaged**: phase-2 judge `z>1.0` used within-window tick-sigma, but
   before/after windows are separated by settle+measure gaps whose drift is 3-10x sigma on this box
   → false GAINs (which keep the flip AND clear probed_mask) → endless churn. Fix: self-calibrating
   null scale `fc->null_abs` = EWMA(1/4) of |after−before| over REVERTED probes (they are literal
   null experiments); gain now requires `z>1.0 && delta > 2*null_abs`; re-open bar `3σ + 2*null_abs`;
   FESC_MEAS_N 10→16.
2. **Watchdog counted event-loop iterations, not time**: tmFlipTick runs per beforeSleep, so the
   "40 ticks ≈ 10s" grow-back park watchdog fired after ~1ms under load — flips aborted before the
   IO thread saw IOEXIT. Fix: `tm_flip_abort_ms` wall-clock 10s deadline.
3. **Aborts were invisible to the controller**: it "measured" the never-applied flip, judged
   NO-GAIN, and "reverted" — an uncommanded net move (observed live: aborted grow-back + revert =
   uncommanded grow-front; explains a desynced 7io/1ex hold). Fix: `tm_flip_aborted` flag; probe
   aborts cancel the probe (no null feed, no probed_mask bit, backoff, other direction next);
   revert aborts re-issue the revert until it lands (checked before the converged-hold block, since
   CONVERGED latches at revert-issue time).
Validation (3min GET → 3min HGETALL shift): flips 70→8, CONVERGED+HOLD engages (9.1M), 0 aborts,
shift re-opens in ~3s and re-converges in 12s at 6io/2ex; HGETALL phase +64% vs the desynced run
(651k vs 396k). GET steady 8.9-9.4M ops/s across both runs.

## 2026-07-23 (cont) — second tripwire round: null poisoning, edge convergence, flip-skew leveling
Relaunched sweep tripped again (118 flips/50min, 0 CONVERGED, p1 stuck −15%). Root causes + fixes:
4. **Null self-poisoning**: feeding |delta| of REVERTED probes into null_abs is circular — rejected
   real gains (p1 grow-front +19%, five times) sustain the very null that rejects them, and real
   losses (p32 −1.7M) inflate it further. Fix: null samples now come from CONSECUTIVE probe
   baselines at the SAME config (honest between-window drift, ~2-4k at p1 vs the poisoned 115k);
   >50% baseline jump = workload swap → reset search context instead of sampling. Plus a 2%
   relative gain floor for the null_abs=0 cold start.
5. **Convergence unreachable at pool edges**: only EX-origin threads flip back (io floor = configured
   io_threads), so the "back" probed_mask bit could never set at the boot config. Fix: unavailable
   directions count as explored; latch moved to probe-launch time (phase-2 judge sees MID-PROBE
   live counts — the revert is async — and lied about baseline reachability). Launch also skips
   re-probing a known-worse direction.
6. **Settle gate measured mid-rebalance**: post-flip bucket moves + cache warmup under-read the new
   config (4io/4ex probed 4.56M vs 5.8M settled) → hill-climb parked in worse configs. Fix:
   reshard_done_seq quiescence gate — settle requires rate plateau AND no reshard completing for
   SETTLE_N (3→5) ticks; WARM_CAP still bounds.
7. **Flip-skew leveling**: a 7io→4io grow-back cascade leaves [8k,4k,2k,2k] bucket counts (LIFO
   neighbour-halving) = 75% of even capacity, and the EWMA outlier balancer is structurally blind
   to it (bimodal skew inflates sigma; cool workers not adjacent to hot). Fixes: (a) exact post-flip
   RELEVEL cascade — while tm_relevel_pending, walk live boundaries vs even-count targets, one O(1)
   range-flip per tick, EWMA balancing paused; (b) DIFFUSE pass as general safety net — steepest
   adjacent-pair imbalance (>0.25*mean) shifts an imbalance-proportional chunk, own settle/streak/
   no-progress state.
Validation (A: p1 GET / B: p32 GET / C: 80f HGETALL, one server session): A 809k conv@7 flips
(+34% vs stuck); B 6.54M avg, holds 6.87M at leveled 4io/4ex — ABOVE the 6.29M churned preflight
and 5.8M skewed baselines; C 457k conv at floor. Total 18 flips, 3 CONVERGED, 2 re-opens, 0 aborts.

## 2026-07-23 (cont) — p32 deficit ROOT CAUSE ablation (10 configs x3, static 4io/4ex, medians)
The −20% "all-features" p32 gap DECOMPOSED (GET M ops/s, median of 3, interleaved):
  orig-w anchor         7.66      (README-era reference)
  HEAD knobs-OFF (A)    7.38   -3.6% vs orig  = unconditional shared-kv code drift
  +mcmd-lock  PRE (B)   6.98   -5.4% vs A     = the lock discipline as shipped
  +mcmd-lock POST (Bx)  7.36   +5.4% vs B     = LOCK-PAD FIX works, now ~1% over knobs-off
  +modes+bal  (C)       6.34   -14% vs A      = **THE DOMINANT OVERHEAD** (flip machinery+balancer)
  all-on PRE  (D)       6.01   -21.5% vs orig = the sweep config (churned)
  all-on POST (Dx)      6.37   -16.9% vs orig = staged fixes so far (lock+struct+gate)
  gate-closed (Ap)      7.39   +1.4% vs Ax    = prefetch-gate basis fix confirmed (cache-resident)
  wpn=1 privKV (F)      7.46   +2.3% vs Ax    = shared-node-db SHARED_MT atomics cost ~2%
REFRAMING: mcmd-lock was NOT the elephant (fixed, ~1% now). thread-modes+thread-balance is −14%,
even holding the SAME 4/4 config a static build uses. Root cause (overhead-review finders, verified):
- **F1 exThread false sharing** (server.h:2113-2152): db@819520 (read per-dispatched-op by IO
  threads) shares a 64B line with w_ewma_vsize (per-op worker write), ops_total, pf caches, and the
  thread-balance-written tm_qdepth_ewma_q4/tm_busy_us. Owner dirties the line every op => IO's db
  read misses cross-core every dispatch; thread-balance adds more per-pass writes to the same line.
  #1 lever. Fix: mirror db into read-only ex_db_base[] + split tm_* onto their own line.
- Secondary: exSlice probes ex_threads-1 dormant growth queues/pass when thread_modes on; per-pass
  depth-probe acquire load + 2 vDSO clock reads under balance; feature-mask to collapse 8-10 per-op
  knob loads; HFE 10-proc-compare chain; dead value-forwarding residue in lookupKeyReadWithFlags.
Fixes staged (uncommitted): lock 64B padding + carried-bucket reuse (server.c ~6030/13975/13834),
client-struct tail reorder (server.h), prefetch-gate per-worker basis (server.c 13726).
OPEN QUESTION being measured now: is C's −14% machinery-active steady cost, or controller-probe
transient in the 75s cell? (converged-hold vs static, same 4/4 — decides fix priority.)
