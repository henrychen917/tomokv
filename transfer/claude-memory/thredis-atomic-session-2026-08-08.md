---
name: thredis-atomic-session-2026-08-08
description: "Atomic stack state after the fable-audit session — ship line, the P0 it found, wakecoal reverted, what's next"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Ship line = branch 2s-mset-atomicity-verepoch (worktree tmp/mset_verepoch), HEAD = the wakecoal
revert on top of bd1a449ba.** Everything below measured static io4/ex4, key-lb 0, memtier t8 c25 p32,
HOT ks=64 unless stated.

**P0 FOUND AND FIXED (the session's most important result).** Pipelined `MSET k v` then `MSETNX k w`
on one connection: atomic ON answered as if k were absent — 3065/4000 wrong replies AND wrong final
state; `MSET d v` then `DEL d` returned count 0 for 3098/4000. **Atomic OFF was correct (0/0/0)** —
the consistency feature was breaking a guarantee stock keeps. Cause: MSETNX's presence probe and
DEL's live lookup are read-then-write but resolve committed-only (`kvobjVersionAt(..., NULL)`), and
`csAtomicReadsSources()` — the ONE list feeding both the TOMO_R_ATOMIC_READ registry flag and the
hold predicate — omitted CS_MSETNX/CS_DEL. Fix needed BOTH halves: adding the ctypes alone measured
as noise (3065→2750) because the predicate tail is
`csAtomicPortallVersionedWrite(c,s) && csAtomicReadsSources(s)` and the portall test excludes the
three original bag ctypes by construction. Now 0/0/0, perf free (bloom overlap filter). Test:
tmp/nx_own_pending.py. NOTE the class: every gauntlet missed it for the whole campaign because every
test used sync round-trips or plain GETs — never a WRITE-SIDE PROBE after a pipelined write.

**WAKECOAL REVERTED — a win that broke another cell.** Retire-side eventfd dedup gave pure MSET
+29% (814k) and 9:1 +10%, soak clean... but it starved the READ-HOLD parks, which share
clients_atomic_window_parked yet are released by a different condition (pending_count==0, not
window_open). Interleaved A/B/A/B on 1:1 hot: prewake 131k/162k/145k vs merged 274/8020/EMPTY
(inflight pinned 442). Branch 2s-atomic-wakecoal @35fefd7bb kept for a fix pass — the armed-flag
dedup must special-case the read-hold release condition. LESSON: the +29% cell and the broken cell
were different workloads; only the full matrix caught it.

**R1a PRUNE-piggyback REJECTED by its own counter** (branch 2s-atomic-r1diet @2ccae7c3a): shipped a
`tomokv_atomic_retire_deferred` gate-opens counter which read 10.1M in a 40s soak (~250k/s), proving
the design's "deferral empty in steady state" premise false; no gain (mset 618k/284k vs base
608k/619k). Hardcode-or-delete ⇒ dead.

**Numbers on the ship line (post-revert):** mset 613k, 9:1 974k, 1:1:1:1 1.13M, 1:1 149k, torn 0,
MSETNX/DEL 0/0/0. vs Dragonfly (~860k mset, ~874k 9:1, ~994k 1111, torn 0.16%): 9:1 and 1:1:1:1 are
WINS with a guarantee dfly does not offer; mset ~-29%; pure MGET needs AUTO threads (1.68M) not
static io4 (1.10-1.16M) to show its win vs dfly 1.41M.

**1:1 is a KEYSPACE artifact, not an 80% loss:** ON vs OFF = ks64 11.9k/1.01M, ks10k 632k/947k
(-33%), ks1M 584k/1.03M (-43%). The hold's structural ceiling is n_conns/commit_latency ≈ 200/1ms ≈
200k, matching the stable 131-162k hot readings. Real unlock = own-resolve (see below), not tuning.

**Design docs on disk (tmp/):** BORROW_READ_DESIGN.md (540 lines; verdict BUILD staged; §11 owner
amendment: WORKER-side borrow is viable, §11.1 correction: the plain-write fallback gate is wrong
under 1:1:1:1 — use the REVERSE BARRIER, the mirror of the shipped read-hold: writes wait for
overlapping in-flight borrowed reads, bloom-scoped, so cost is proportional to OVERLAP only);
WRITE_COST_DESIGN.md (commit-section is the wall: 16 stamp-lane pushes/MSET8 inside commit_lock ⇒
~570k/s serial ceiling ≈ the measured wall).

**KEY INSIGHT linking 1:1 and borrow:** the read-hold and the reverse barrier are the same
serialization pointed opposite ways; both cost only on OVERLAP. So measure the actual overlap rate
in target workloads (a counter on the bloom intersection test, no implementation needed) — it decides
BOTH the 1:1 outlook and whether borrow ships, before writing the hard part.

**Quarantined:** branch 2s-atomic-ownread (own-resolve) — the right idea for 1:1, but 3 confirmed P0s
(dispatch-pinned snapshot vs stamp-cleared origin; plainGET RYOW 2/5000; window pinned at 512 under
sustained 1:1). Agent fix 3f4cea426 (origin-identity, immutable through stamp) landed but unvalidated.
Also open: P1 duplicate-key retire leak (DEL k k / MSET k a k b ⇒ equal-seq versions no prune retires);
P2 SCAN/KEYS/DBSIZE/RANDOMKEY don't resolve bags; the window=1 park-readmit reply hole (never
root-caused, agent died). Related: [[thredis-atomic-window]], [[thredis-flip-controller-frozen]].
