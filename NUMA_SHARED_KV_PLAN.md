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
  node_dbs[w/wpn]; spare slot private), KVSTORE_SHARED_MT (atomic aggregates, Fenwick skipped +
  linear-scan fallbacks, rehash-list spinlock, release-published dict creation), per-node FLUSH
  rendezvous barrier, worker-range RANDOMKEY, node-summed DBSIZE, per-worker-range KEYS subs, and
  **reshard = drain-fence + O(1) ownership flip** (no scan, no log, no cleanup; cross-node/spare
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
- KNOWN GAPS: estore (HFE) aggregates not MT-safe on shared dbs; thread-modes SPARE activation
  into a shared node is rejected (private array) pending integration; S2 keyspace-wide ops
  (SCAN on shards) unchanged.
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
- **DEBUG RESHARD PERWORKER protocol desync fixed** (arraylen=alloc vs loop=num_workers -> CLI hang
  when the spare slot is allocated).
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
