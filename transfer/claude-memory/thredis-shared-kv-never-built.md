---
name: thredis-shared-kv-never-built
description: Shared-keyspace was designed-but-unbuilt until 2026-07-22; NOW BUILT on 2s-numa-shared-kv-dev (per-NODE dbs, O(1) flip reshard, node-local stock exec)
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**UPDATE 2026-07-22 (later same day): NOW IMPLEMENTED on `2s-numa-shared-kv-dev`** through commit
`1351c2baa`, per the user's model ("4 nodes 4 cores => 4 physical dbs, 16 virtual buckets; lock
every time, never contend"):
- **S0.2a** (`1ecf550f7`): dict index == bucket (xxh64&16383), 16384-dict kvstores; getKeySlot tomo
  branch with NO client slot cache (multi-key cmds span buckets). Gates: corruption+intercard PASS,
  perf wash.
- **S0.2b+S1** (`06a1b8619`): ONE physical db per NODE (`ex_dbs[w]` aliases `node_dbs[w/wpn]`,
  spare private); KVSTORE_SHARED_MT = atomic aggregates + Fenwick SKIPPED with linear fallbacks
  (the ITERATOR depends on Fenwick — can't just skip) + rehash-list spinlock; per-node FLUSH
  rendezvous barrier (zero-bucket slots skipped = wedge-proof); worker-range RANDOMKEY; node-summed
  DBSIZE; per-worker-range KEYS subs (full walk double-counted wpn× + raced siblings); **reshard =
  drain-fence + O(1) table flip** (no scan/log/cleanup; cross-physical-db arms rejected). Gates: 10
  flips under 951k concurrent ops 0 errors; corruption PASS at MAX sharing (numa=1: 4 wkr 1 kvstore);
  perf GET 1.02x/SET 1.05x.
- **Payoff** (`1351c2baa`): same-NODE reads run the STOCK proc under ALL node worker locks
  (ascending = cycle-free), byte-exact incl. stock side-effects. MEASURED gate admits only winners:
  SETOP-INTER/SINTERCARD/ZINTERCARD/TOUCH (SINTER +40-51%, SINTERCARD +25%); SUNION 0.61x + ZINTER
  0.87x LOSE (unions parallelize on IO threads; largest-driver fold beats stock) => stay on
  reference paths. MGET/EXISTS stay on the fine-grained borrow.
- **Deterministic repro for the PRE-EXISTING mass-kill livelock**: ~10 reshards under load + kill
  16 bench conns + FLUSHALL => all-threads-R. Bisected: identical on the S0.2a parent (the known
  freeClientsInAsyncFreeQueue livelock, not the new code).
- KNOWN GAPS: estore/HFE not MT-safe on shared dbs; spare-into-shared-node rejected; SCAN (S2)
  unchanged; ptrace blocked (yama=1) — gdb needs sudo on this box.
- **Per-node flip LIVE** (`086569bb5`): per-node live prefixes (tm_node_wlive + tmWorkerLive
  predicate; global-prefix consumers converted: RANDOMKEY/KEYS-fan/autotuner/DEBUG/FLUSH); actuators
  tomoGrowFrontNode/BackNode (node's highest live worker, LIFO); test hook modeshift-test 70+n/80+n
  (n<10). Validated both nodes independently 2/2<->3/1 under load. Same algorithm any wpn>=2.
- **Controller inputs FIXED** (`a45bbe74d`): idle ticks polluted EWMA variance (sigma was 2x mean =>
  z-gates noise); now idle ticks freeze mean/var + probes need offered pressure + priming waits for
  nonzero rate (inst gates on ops_prev_ms baseline NOT primed — chicken-egg trap). Sigma now 0.5-1%;
  monotone climb to 7io/1ex, settled-flip GET beats static ~9% (matrix 0.92x was mid-climb artifact).
  Remaining: convergence-LOCK never engages (probe-revert churn at optimum), seed-burst overreaction,
  probe-cost accounting — the "flip algorithms" study TODO.
- **MGET/EXISTS borrow beats stock node-locked path** (A/B knob tomokv-mcmd-nodelocal): 0.81-0.93x —
  group machinery dominates at small N; borrow stays.
- **Adversarial review round 2 (`9e1e9612d`)**: 15 confirmed root causes, 14 fixed. Headliners:
  ONE `tomo_flush_gate` closes 3 deadlocks (concurrent-flush cross-barrier; main-thread flush-vs-
  migration — waiting flushers must PUMP reshardCoordinatorTick+tmFlipTick when on main; flush-vs-
  flip TOCTOU — reshardArm refuses while gate held, last barrier participant releases). Converted
  workers now DRAIN their dormant EX queues in IO mode (straggler-sub group-hang). HFE = node-locked
  exec under mcmd-lock / error without. tempDb needs 14-bit kvstores in tomo mode (replica swapdb
  OOB). Hash-carry hint gated behind CLIENT_EX_PENDING (real clients never init it). RANDOMKEY:
  bucket-range-width weights + own-lock around expire-delete. SHARDNUMSUB slot 0 in non-cluster.
  Global grow hooks refused on multi-node. numa-nodes capped 16. Balancer cron → tmWorkerLive.
  Accepted: flush stops the node for the free's duration. Fix validation all green (no-deadlock
  repros, 108/108, harness PASS, 60s stress clean, perf parity 0.991/1.006/0.997 across campaigns).
- Bench matrix (means, single-CCD): shared-vs-original-physical-shards OVERALL geomean 0.986 =
  parity; n2-vs-n1: MGET8 0.77x (split cost), MSET8 1.11x (2 kvstores halve write-aggregate atomic
  contention); flip GEThot +6-9% the one consistent flip win. RESHARD SERVICE IMPACT (2M keys, 1/8
  range, concurrent GET): copy engine craters worst-sample to 837k (-45%); O(1) flip stays 1412k
  (-7%). Wall ties (~270ms both = coordinator phase latency, not data) at 64B values; copy is
  O(keys*size), flip size-independent.
- **CRITICAL fix `ac5738bb9`: non-pow2 worker counts were entirely broken** (pre-existing):
  ex_bucket_end floor formula disagreed with ex_bucket_table on boundary buckets unless W|16384 =>
  reshardRangeValid rejected EVERY arm on 3/6/12-worker configs (no flips/balancer). All prior
  validation used pow2 and never saw it. Fix: end[i]=ceil((i+1)B/W).
- **Any-core pool** (same commit): boot 1io+(cpn-1)ex per node => every non-base core flips both
  ways; guards = the >=1io/>=1ex constraint. Validated numa=2 cpn=4 full range both nodes
  independently. **io-vs-ex flip direction chooser** (user design): steady-state io/ex rates are
  equal so their difference IS the qd trend — standing queues => grow back, dry => grow front;
  validated (GET => FRONT, climbs to 7io/1ex 1.73M). GOTCHAS: CONFIG SET with unchanged value
  no-ops (toggle through 0 between modeshift-test repeats); DEBUG RESHARD PERWORKER desync fixed.

---- Original finding (context) ----
Correcting a recurring misconception (user believed "each node shares 1 db" was live and made EWMA
reshards cheap): **it was never built.** The `2s-shared-keyspace-dev` branch only ever shipped
**S0.1** (`TOMO_BUCKETS` 4096→16384, commit `6060c4d67`). The stages that create the shared db and
the cheap reshard were designed in `SHARED_KEYSPACE_DESIGN.md` but NOT implemented:
- **S0.2** = collapse per-worker 1-dict kvstores (`ex_dbs[w][j]`, `slot_count_bits=0`, each worker
  physically isolated) into ONE shared 16384-dict kvstore per db.
- **S1** = delete the copy engine; reshard = O(1) `ex_bucket_table[b]` flip, no key copy.

PROOF it's unbuilt (verified 2026-07-22): `migApplyOne` (server.c:~9008) still does `rdbLoadObject`
+ `dbAdd(bdb,…)` — reshards physically COPY every key between isolated per-worker kvstores. So a
bucket move is O(keys-in-range), not O(1). The mcmd-lock per-node borrow (see
[[thredis-mcmd-lock-pernode]]) exists BECAUSE the dbs are per-worker-isolated (a node has
`ex_per_node` separate kvstores, does NOT share one db). All the flip/mcmd-lock branches
(`2s-numa-dev`, `2s-numa-mcmd-lock-dev`) sit ON TOP of shared-keyspace-S0.1, so they inherit the
finer buckets but NOT a shared db.

Implementing it: forked **`2s-numa-shared-kv-dev`** (2026-07-22) with `NUMA_SHARED_KV_PLAN.md` — a
staged plan S0.2a (route dict-selection by `xxh64(key)&16383`, the same value ex_bucket_table keys
on — today the fake's `->slot` is the CLUSTER CRC16 slot used at server.c:6722 `kvstoreGetDict`,
collapsed to dict 0) → S0.2b (one shared kvstore + partition the kvstore aggregates
`cumulativeKeyCountAdd` key_count/non_empty/Fenwick per-worker, the design's "one real cost") →
S0.2c (expires + DBSIZE/KEYS/RANDOMKEY) → S1 (O(1) flip + aggregate handoff). Each stage byte-exact,
gated by `harness/xshard_corruption.sh`. Only after S1: the cross-shard payoff (stock proc / borrow
over the shared kvstore — the original "implement the rest" ask rides on this). NOT a small add-on.
