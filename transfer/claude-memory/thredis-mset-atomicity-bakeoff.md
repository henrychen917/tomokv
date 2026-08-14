---
name: thredis-mset-atomicity-bakeoff
description: "cross-shard MSET atomicity 3-way bake-off — epoch-versioned MVCC won (reader+writer atomic, ~free); knob tomokv-mset-atomic"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Owner wanted optional cross-shard MSET atomicity (today's cross-shard MSET is lock-free
scatter-gather = best-effort, a reader can tear it). Prototyped THREE mechanisms as Codex forks off
5b1763075, each its own branch/worktree, then benched saturated (memtier auto mode, initial io4 ex4,
8t x 25c x pipeline 32 = 200 conns, mixed MSET:GET), HOT keyspace=64 (heavy overlap) vs COLD=100000
(disjoint):

| approach (branch / worktree) | HOT MSET | torn | guarantee |
|---|---|---|---|
| Dragonfly intent-lock (2s-mset-atomicity / mset_atom) | -25% | 0.3% | writer-side only (readers tear) |
| **epoch-versioned MVCC (2s-mset-atomicity-verepoch / mset_verepoch)** | **-1.6%** | **0.0%** | **reader snapshots + commit-ordered writers (full)** |
| optimistic seqlock (2s-mset-atomicity-seqlock / mset_seqlock) | -1.1% | 0.0% | reader-safe only (overlapping writers can mix final) |

**WINNER: epoch-versioned MVCC.** Reuses THredis's QSBR retire-not-free (old value stays readable in
grace) + a global commit_seq frontier: MSET stamps new values with a ticket, advances commit_seq in
order = the atomic commit point; MGET snapshots commit_seq and reads <=snap per key. Full Redis MSET
atomicity at ~-1.6% under contention (dfly's per-key intent lock craters -25% HOT). No version leak
(+3MB RSS under a 10s hammer, then flat -> grace reclaims predecessors). seq is a hair faster but
reader-only; dfly loses on both axes. Knob **tomokv-mset-atomic** (default OFF, zero-cost off) added
on the verepoch branch; designed to extend to tomokv-mget-atomic later.

**2026-08-07 RE-TEST at 8s sampling (the 3s bakeoff under-sampled the tear): epoch's win is STRONGER
than the table above.** base/seq/epoch, 2 writers + reader, 8s, reorder 0 AND 3, 3 reps each (~2M
reads/arm): **epoch torn = 0.000% across ALL 6 reps** (commit_seq snapshot never retries ⇒ cannot
leak). **seqlock torn ~0.6-1.5% — essentially the SAME as base (~0.1-2.0%)**: its optimistic
per-key validate EXHAUSTS its retry cap under two-writer contention and returns torn snapshots, so it
is barely better than no atomicity. The bakeoff's "seq torn=0.0%" was a 3s under-sample. So seqlock
is NOT reader-safe in practice; **epoch is the mechanism, decisively.** seqlock DROPPED. (Aside:
`final_state=ALL-SAME` even for base — the last uncontended write completes cleanly ⇒ weak
discriminator; torn_reads is the one that separates them.) NOTE: verepoch epoch is currently
ALWAYS-ON — the `tomokv-mset-atomic` knob (KNOB_SPEC.md) was specced but NEVER committed (branch has
only 4bd68e0b5 epoch + reorder-fix cherry-pick); the knob still owes. See [[thredis-reorder-ryow-fix]].

**2026-08-07 write-saturation CRATER (the bakeoff's -1.6% was mixed-only, never stressed pure MSET).**
On mset_verepoch: knob `tomokv-atomic` (default off) added (0c658c6b1); version state moved to one 8B
pointer to a lazy record (7e1697874) => OFF heap tax +25.8%->+10.6% (halved), reshard-safe INTRA-node
by construction (metadata rides the object; per-worker out-of-band table was REJECTED — key-LB owner
flip strands it). Then found: **pure saturated atomic MSET8 craters to ~5k/s (OFF ~1.2M, -99.6%)** —
both inline AND +8B, HOT and COLD, PING stays instant (not wedged, just slow). Root cause is NOT a
lock: an atomic MSET's +OK can't publish until its ticket AND every earlier ticket commit (in-order
frontier = linearizability: reply implies visibility), and under saturation a group stalls on its
slowest owner's deep queue => throughput = in-flight/latency ~= 12k. INHERENT to commit-ordered
airtight MVCC. The bakeoff's -1.6% was a mixed 1:8 MSET:GET run (tiny MSET pressure); MGET-ON is
genuinely ~-1.5%. Extracted win: reclamation moved OUT of the commit spinlock (909389964, was O(n)
zfree under the flag) = 2.8x on the crater (5k->14k), airtight preserved. Flat-combining try-lock was
safe (no wedge, torn=0) but NEUTRAL (bottleneck is the ordering, not lock contention) => REVERTED per
hardcode-or-delete. NET: atomicity is cheap for reads/mixed, capped for write-saturation; it's opt-in.
See [[thredis-reorder-ryow-fix]], [[user-hardcode-or-delete]], [[thredis-worker-overhead-bound]].

**2026-08-07 COMPETITOR COMPARISON settles the crater question (owner's idea): it is a GUARANTEE-vs-
SPEED spectrum, NOT a THredis defect and NOT a physics wall.** Atomic MSET8, 200 conns, HOT ks=64,
same 6s torn test — reader-torn% / atomic-MSET-per-s:
  THredis-OFF (default, best-effort)  1.66% / ~1.0M
  Garnet 2.0.1 (shared store+latching) 0.62% / 2.2M
  Dragonfly v1.39 (sharded, VLL txn)   0.13% / 820k
  THredis-ON (epoch, global frontier)  0.00% / 11k
All four are writer-atomic (final ALL-SAME). Dragonfly/Garnet are fast because they STILL TEAR reads
(0.13-0.62%) — they do NOT give MGET a torn-free snapshot. THredis-epoch is the ONLY system at
torn=0, and the ~70-200x crater is the price of that last fraction. Conclusion: THredis's DEFAULT
(OFF) is already competitive (≈Dragonfly speed, comparable guarantee); the epoch is a PREMIUM opt-in
guarantee no competitor offers, not a competitive gap. So the write-saturation crater is NOT an issue
we must solve. Four perf fixes were tried and only one kept: flat-combining the commit drain (safe but
NEUTRAL, reverted), deferred/SI reply (near-no-op, reverted), lock-free ticket ring (crater persisted,
reverted) — the crater is inherent to the global-frontier torn=0 design; ONLY reclamation-out-of-
spinlock stayed (909389964, real 2.8x on the cratered path). A fast near-airtight mode would require a
Dragonfly-style per-shard-transaction rebuild (separate project, and it would still tear ~0.13%).
HARNESS TRAPS hit: `pkill -f dragonfly-x86` SELF-MATCHES the running shell (its cmdline contains the
string) => kills your own command (silent exit 1); dragonfly comm truncates to `dragonfly-x86_6` (15ch)
so `pkill -x dragonfly` misses it and it squats the port => measure-the-wrong-server; kill by captured
PID or by `ss :port`. Garnet runs via `DOTNET_ROOT=/home/henry/.dotnet dotnet GarnetServer.dll` (net10).
See [[thredis-selfmatch-and-lock-traps]], [[thredis-forwarding-abandoned]], [[user-hardcode-or-delete]].

Benching lessons (all bit this session): memtier's multi-`__key__` MSET DOES generate distinct keys
(confirmed by the ~1M/s cross-shard rate vs ~7M single-key). MONITOR is unreliable in the sharded
model (monitor client misses worker-executed commands). STATIC thread mode oversubscribes: io4+ex8 =
12 busy-poll threads on 8 cores => every binary craters to ~42K (artifact) -> use AUTO mode (flip
controller keeps total fixed within the pinned cores), per [[thredis-saturated-benching-rule]]. Two
concurrent `codex exec` collide on a shared screen session -> run sequentially; launch each from a
nohup'd wrapper script (foreground codex), not a direct `nohup codex &`.
