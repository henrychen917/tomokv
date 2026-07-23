# M-command lock-borrow execution (2s-numa-mcmd-lock-dev)

User directive (2026-07-22): for multi-key ("M") commands (MGET, MSET, DEL, EXISTS, SINTER, …),
instead of the current scatter→worker→gather, try **lock-borrow**:

- **Scatter twice**: (1) bucket→node routing, then (2) within a node, one executor walks the keys.
- **One executor per node** runs the whole M-command under **per-bucket locks** (all same-node
  threads coordinate on shared buckets via locks).
- **Keep buckets**: bucket ownership stays; single-key ops stay on their owner. The lock is only a
  *rare-path* safety mechanism — because buckets are single-owner, a borrower almost never collides
  with the owner, so the lock is essentially always uncontended (cheap CAS).
- **Backlog, don't spin**: if a key's bucket lock is contended, DON'T wait — push that key to a
  backlog and proceed to the next key (different bucket, ~always free). Drain the backlog after the
  first pass. Work-conserving, no spin.

## Why it might win
The scatter-gather path pays: split into N sub-fakes, dispatch to N SPSC queues, N workers execute,
gather + reorder N replies. For random keys that's N cross-thread round-trips per command. Lock-borrow
does it in ONE thread with N (uncontended) lock/read pairs — like stable's single-threaded MGET but
safe alongside the sharded workers, and it avoids the gather/reorder. Measured baseline (this box,
io6ex2): MGET3 numa 3.52M vs stable 2.17M (numa already wins at io-heavy), MGET16 1.11M — the gather
overhead grows with key count, which is where lock-borrow should help most.

## Correctness challenges (must handle)
1. **Rehash-on-read**: dictFind rehashes one step (mutates the dict), so read-read is NOT safe. The
   borrower AND the owner must hold the bucket lock even for reads → lock cost lands on the single-key
   hot path too. Mitigation: keep the lock a 1-byte CAS; gate the whole feature behind a knob so the
   default lock-free path is untouched when off.
2. **Owner ⇄ borrower mutual exclusion**: owner takes the bucket lock for every op when the knob is
   on; borrower takes it per key. Uncontended CAS ≈ 20-40 cyc.
3. **Migration interaction**: a bucket mid-reshard (drain fence) must not be lock-borrowed — fall back
   to scatter for keys in the migrating range (reuse migBucketInRange).
4. **DB access from a non-owner thread**: the borrower reads `exThreads[owner].db` directly; safe
   only under the bucket lock + no concurrent rehash from the owner (owner also locks).

## Prototype plan (incremental, knob-gated `tomokv-mcmd-lock`, default 0)
- **S1**: per-bucket lock array `_Atomic uint8_t bkt_lock[TOMO_BUCKETS]` + trylock/unlock helpers.
- **S2**: owner hot path takes the bucket lock around a key op WHEN the knob is on (exSlice per-op).
- **S3**: lock-borrow MGET read path on the IO thread: for each key, trylock bucket → lookupKeyRead
  on the owner's db → copy value → unlock; contended → backlog; drain backlog. Compare byte-exact to
  the scatter-gather result.
- **S4**: measure MGET/SINTER lock-borrow vs scatter, and the single-key GET/SET overhead of the
  always-on lock. Keep only if M-commands win enough to justify the hot-path lock cost.
- **S5** (if S4 promising): per-node M-executor thread + the 2-level scatter; writes (MSET/DEL).

Start: S1 + knob, then S3 read-only MGET prototype, measure, iterate.

## S1+S3 prototype results (2026-07-22, io6ex2, pure-MGET so workers idle = safe without S2)
Lock-borrow MGET is BYTE-EXACT with scatter-gather; crash=0. Gain vs scatter by key count:
  MGET1 +22% | MGET2 +26% | MGET4 +25% | MGET8 +12% | MGET16 +3% | MGET32 ~0%
INSIGHT: lock-borrow removes the FIXED per-command scatter/gather overhead (group create + N
dispatches + gather + reorder), which dominates for SMALL MGETs (the common case) => big win. At
high N the real read work dominates and scatter's PARALLELISM (N workers read at once) catches
lock-borrow's single-thread serial read => crossover ~N=16-32. So lock-borrow is a clear win for
small-to-medium multi-key commands, neutral for very wide ones.
COROLLARY: with lock-borrow the workers just HOLD data (IO threads read directly), so the io/ex
optimum for M-heavy workloads shifts toward io (more readers); io7ex1 may beat io6ex2 for pure MGET.
NEXT: S2 owner-side bucket lock (for MIXED workloads with concurrent single-key writes — currently
only pure-MGET-safe); measure the single-key GET/SET hot-path lock cost; then hybrid (lock-borrow for
small N, scatter for wide N); per-node executor (S5); extend to SINTER/EXISTS/writes.

## S3' WORKER-borrow (2026-07-22, user redesign: move exec off IO onto the EX thread)
IO dispatches the WHOLE MGET to the FIRST key's owner worker (getWorkerForCommand hashes argv[1]);
that worker borrows the other keys under per-worker locks and executes on-thread, replying via the
normal worker drain (exExecFake routes an mcmd_lock MGET fake to tomoMgetLockBorrow). Different MGETs
go to different first-key owners => execution SPREADS across all workers. Byte-exact; mixed SET+MGET
integrity 5/5, crash=0.
RESULT (scatter vs worker-borrow):
  io6ex2 (2 workers): MGET1..16 = +24/+20/+17/-6/-21%  (few workers => few executors => loses at high N)
  io4ex4 (4 workers): MGET4/8/16 = +105/+83/+43%
  io2ex6 (6 workers): MGET4/8/16 = +190/+241/+216%
KEY INSIGHT: scatter makes MGET favor IO-heavy (the few IO threads bottleneck on gather); worker-borrow
FLIPS it — MGET now favors WORKER-heavy, because the workers do the parallel borrow-execution and the
IO threads only dispatch+combine. Worker-borrow's BEST config (io4ex4 MGET8=2.38M) beats scatter's BEST
(io6ex2 ~1.92M) by ~24%, AND frees the IO threads AND is multi-node-ready. So for M-command-heavy
workloads the io/ex optimum shifts to worker-heavy — the opposite of single-key GET.
NEXT: per-node scatter+combine (multi-node: one first-key-owner PER NODE, IO combines partials);
extend to SINTER/EXISTS; single-shard/1-key MGET short-circuit (MGET1==GET1); hybrid vs scatter at
very high N on few-worker configs.

## S3'' PER-NODE scatter+combine (2026-07-22) — DONE + VALIDATED (numa_nodes>=2)
tomoMgetPerNodeDispatch: groups the MGET's keys BY NODE (node = tmNodeOfWorker(owner)), issues ONE
borrow-exec sub per non-empty node dispatched to a node-local worker (the node's first-seen key
owner). Each sub carries its node's keys + their ORIGINAL positions and reads each key from its TRUE
owner db under that owner's per-worker lock (csSubExec CS_MGET g->mcmd_borrow branch), writing the
value COPY into mget_vals[pos]; the IO drain reassembles in key order (csReassemble) — REUSES the
coalesced MGET group machinery (mget_vals + mget_pos + CS_MGET reassemble/teardown), the only new
piece is the per-key borrow read. Every borrow stays NODE-LOCAL (no cross-node db reads) — the point
of the split; on real NUMA that keeps the remote-memory reads out of the hot path.
ROUTING: numa_nodes>=2 AND >=2 keys => per-node group; else (numa_nodes==1, or MGET1) => the S3'
single-worker borrow (tomoMgetLockBorrow, whole fake to the first key's owner). MGET1==GET1 (single
path, no group alloc).
VALIDATION (io2ex2/node = io4ex4, 2 logical nodes): per-node borrow BYTE-EXACT vs scatter across 60
varied MGETs (2-50 keys, present+absent mix, 1553 reply lines); 20s concurrent stress (16-conn SET
writers @ ~107k rps churning the SAME keyspace + 8303 multi-node MGET reads) => 0 reader errors, 0
asserts/segv, server alive — the per-worker lock coordinates the node-local borrow read with the
owner's concurrent single-key SET (S2 lock), no rehash-during-borrow crash. numa=1 regression: still
byte-exact, GET/SET 118-121k, no crash. GET/SET/MGET1 sanity clean on numa=2.
SEMANTIC NOTE (shared with S3' single-node borrow): the borrow read uses LOOKUP_NOEFFECTS (pure read
— it must not lazy-expire/LRU-mutate a NON-owned db from the borrower thread), so a logically-expired
key still returns its value until the owner's active-expire cycle (scatter's LOOKUP_NONE would report
nil + delete). Accepted, consistent property of the whole lock-borrow experiment (knob default OFF).
EXTENDED to EXISTS (2026-07-22): tomoMgetPerNodeDispatch generalized to tomoMPerNodeDispatch(head,
ctype) covering the independent-per-key READ family — CS_MGET (value copies -> mget_vals[pos]) and
CS_EXISTS (present-count -> g->rcount). Same node-grouping + node-local borrow skeleton; EXISTS skips
the position slots (a count needs no order). EXISTS routes through the per-node path for BOTH numa
modes (nn==1 => one sub = a single-node EXISTS borrow); MGET keeps its cheaper single-worker fast path
(tomoMgetLockBorrow) for numa==1. VALIDATED: EXISTS+MGET byte-exact vs scatter on numa=1 AND numa=2
(100 mixed present/absent cmds each), concurrent stress (16-conn SET writers @ same keyspace +
EXISTS/MGET borrow readers) 0 errors / 0 crash / alive on both.
NEXT: extend to SINTER/SETOP (gather members under lock -> setmem) and to WRITES (MSET/DEL) — writes
need the scattered write-subs to ALSO take the owner lock (currently only single-key ops do, via
exExecFake S2; a per-node MGET/EXISTS borrow is safe against single-key writes but NOT against a
concurrent scattered MSET/DEL sub on the same worker db — a known gap while only reads are borrowed).
Bench per-node vs scatter on real NUMA (on this single-CCD sim there is no remote-memory penalty, so
the split shows correctness + parity, not the NUMA-locality speedup it targets).

## Per-node bench + stress (2026-07-22, io4ex4 = io2ex2/node, 2 logical nodes, single-CCD sim)
SANITY-GATE note: unpipelined -c16 caps at ~100-120k rps (load-gen/latency bound, == the GET baseline)
— that regime cannot reveal server-side differences. SATURATED bench uses -P16 -c16 (server-bound,
millions rps, matches the design-doc MGET range). Best-of-2 interleaved, borrow(mcmd-lock=yes) vs
scatter(mcmd-lock=no) on the SAME server (100k keys):
  MGET4 0.98x | MGET8 1.11x | MGET16 0.98x | MGET32 1.17x
  EXISTS8 0.98x | EXISTS16 0.92x | EXISTS32 0.95x
=> PARITY (0.92-1.17x, within the ~15% run-to-run drift on this box). Expected: a single physical CCD
has no remote-memory penalty, so per-node's NUMA-locality advantage cannot manifest here — the result
is "no gross overhead from the per-node group split", NOT a speedup. The NUMA-locality payoff is
untestable until real multi-CCD hardware (Threadripper). (MGET32 +17% hints the borrow's fewer
cross-thread round-trips help at high N even without NUMA, consistent with S3'.)
INTEGRITY STRESS (60s, mcmd-lock on): 8 writers holding the invariant key:i==v-i (incl. 10% DEL+reSET)
+ 6 readers issuing MGET+EXISTS and ASSERTING every non-nil key:i reads back v-i and every EXISTS
count <= arity => 2,351,627 ops, 0 integrity errors, 0 asserts/segv, server alive. Confirms the
borrower/owner per-worker-lock coordination yields no torn / wrong-slot / stale-worker reads under
concurrent single-key SET+DEL writes.

## Adversarial code review (2026-07-22, max, wf_b9329c3c) + FIXES
The review found the borrow read broke the single-writer-per-worker-db invariant against MORE writers
than the initial validation exercised. THE UNIFYING FIX: when mcmd-lock is on, EVERY worker-db access
(not just the single-key S2 path) takes tomo_wkr_lock. All gap sites run ON the draining worker, so
they lock worker->id — inert when the knob is off (predicted-not-taken branch; default path unchanged).
  [F1 CRASH] scattered multi-key WRITES (MSET/DEL/*STORE) AND reads (SETOP/KEYS gather) run via
    csSubExec with NO lock => their dictAdd/dictFind rehash races a borrower on the same worker.
    FIX: the drain wraps csSubExec in tomoWkrLock(worker->id) for non-borrow subs (borrow subs self-
    lock per key). VALIDATED: 30s concurrent cross-shard MSET+DEL(multi-key) + MGET/EXISTS borrow =>
    884,977 ops, 0 integrity errors, no crash (this crashed before the fix).
  [F2 CORRECTNESS] TOUCH shares CS_EXISTS but its POINT is the access-time bump; borrow's
    LOOKUP_NOEFFECTS (==NOTOUCH) silently dropped it. FIX: borrow only genuine EXISTS
    (fake->cmd->proc==existsCommand); TOUCH falls back to scatter. VALIDATED byte-exact + count=3.
  [F4 CRASH] migration db mutations on worker threads (migApplyOne on dst; migServiceScanA cold-scan
    + migCleanupDeleteRangeA range-delete on src) run from the drain, NOT the S2 path, so they race a
    borrow read of the same worker. FIX: migApplyOne self-locks per entry (short hold, keeps the
    64-entry migDrainB batch interruptible); scan+cleanup lock at the drain call site (scan is 64
    keys/call, cleanup one-shot). VALIDATED: 8 populated within-node migrations (w2<->w3, real data,
    36 ARM/FLIP/CLEANUP/DONE) driven to DONE while 1,259,685 MGET/EXISTS borrow + SET ops ran =>
    0 integrity errors, no crash, byte-exact (dbsize + endpoints intact).
  [F3 ACCEPTED] LOOKUP_NOEFFECTS expiry divergence (expired-unreaped key reads present/stale vs
    scatter's nil+delete) — the intrinsic, documented lock-borrow semantic, shared with the single-
    node borrow; the knob is default-off. Not fixed by design.
NET: with the knob on, the borrow read is now safe against single-key ops, scattered multi-key
reads+writes, AND online migration. Set-op/store BORROW (vs scatter) and real-NUMA bench remain TODO.
