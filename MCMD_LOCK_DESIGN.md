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
