---
name: thredis-session-2026-08-08-overnight
description: "Overnight 2026-08-08: atomic validated vs OFF/dfly, +19% mixed from two fixes, commit-diet refuted, flip P0 found, my flip targets were wrong"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**ATOMICITY IS PROVEN, AGAINST A CONTROL THAT DISCRIMINATES.** 126-cell matrix, ON vs OFF vs
Dragonfly 1.39.0, worksets hot64/warm10k/cold2m, configs io4ex4/io2ex6/auto. Atomic ON torn=0 in all
8 configs; atomic OFF torn 3,390-9,638 (18-43% of reads); Dragonfly torn 153-170 (0.40%). Every
earlier "0 torn" was vacuous by comparison — this is the first run where the gate demonstrably opens.
Cost profile: pure reads FREE (mget 0.98-1.04x of off at every workset), pure writes a flat ~35%
(0.59-0.71x, keyspace-independent), mixed worse than either (the read-hold). vs dfly at io4ex4 we WIN
9:1 (1.14x) and 1111 (1.20x) at hot64 and mget at cold2m (1.12x); we lose mset (0.61-0.75x).
**auto is the biggest MGET win** (warm10k 1.46x over atomic-off, 1.38x over dfly) — but see the P0.

**TWO ATOMIC FIXES, BOTH VALIDATED, BOTH SHOULD MERGE.** 2s-atomic-sigexact @7c1bfb826 (exact key
check behind the saturated 64-bit filter) and 2s-atomic-sigexact2 @01941c452 (close the detached-head
window). Combined: 1:1 ks10k and ks2M **~+19%**, 9:1 net ~0% (the second cancels the first's -1.8%),
1111 +14.8%. Correctness zero everywhere (0 torn over ~350-475k probe reads, 0 RYOW, 0 MSETNX/DEL).
Census proves engagement: held/pending 74.6%->0.85% then held -97.7% with conserv exactly 0.

**COMMIT-SECTION DIET REFUTED BY ITS OWN COUNTER** (2s-atomic-commitdiet). stamp_visits/group fell
16->7.2 exactly as designed, stamp_entries/group stayed 16.0, stamp_full 0 — and throughput did not
move (mset8 638201->637725, 635348->636930). So the commit lock's owner-lane pushes are NOT the MSET
wall; WRITE_COST_DESIGN.md's ~570k/s serial-ceiling derivation matched the measured wall by
coincidence. DELETE. Untested candidates left: per-key version-bag install (kvobj+vmeta alloc), QSBR
retire, and the stamp DRAIN (worker side — the diet only touched the push side).

**MY FLIP CONFORMANCE TARGETS WERE WRONG — the controller was right.** I built the target set from a
static curve sampled at 4 configs (io7/ex1, io4/ex4, io3/ex5, io2/ex6). The controller searches all
8 and kept landing on io6/ex2 and io5/ex3, which I had never measured and scored as failures. Filled
in: GET p1 optimum is **io6/ex2** (841894 vs io7/ex1 836885); ZRANGE(100) p1 optimum is io5/ex3
459678 ~= io4/ex4 460165 (tied). So 2 of 3 "failures" were my measurement error. The REAL defects,
both on writes: SET p1 lands io6/ex2 4/4 (io7/ex1 is best, **-3.4%**), SET p32 lands io3/ex5 2/4
(io4/ex4 6780943 is best, **-12.4%**). LESSON: never grade a search against a sparser sample than
the search covers.

**WORKER-ONLY TRIGGER (tomokv-flip-signal 0/1/2/3 on 2s-flip-ramp @3c0a608d6): better on 4 of 6
cases, structurally blind on 1.** Blind case predicted from the code BEFORE measuring and confirmed:
entering ZRANGE p1 from a settled io7/ex1, modes 1/2 never leave (-42% vs optimum) because u_ex is
hard-capped at 1.0 and QCAP is 2048 on every config while closed-loop in-flight work is bounded by
conns x pipeline — so at p1 the worker signal is MOST COMPRESSED EXACTLY WHEN THE WORKERS ARE MOST
OVERLOADED. Mode 3's clip repair recovers it 1 of 2. Conclusion: "delete the io side" cannot be done
as stated; the defensible design is direction from the worker signal, magnitude from the ratio ONLY
in the clipped state.

**ZRANGE HAS NO SINGLE OPTIMUM — it is a ridge in (reply size x pipeline depth), and the peak is
NON-MONOTONIC in reply size.** 2000 keys, ops/s: at 100 members p32 the peak is io2/ex6 (779,659,
reproducing 780,879 from a separate boot) and the spread io7->io2 is 2.7x; at 1000 members p32 the
peak moves BACK to io4/ex4 (104,383) because throughput falls ~7x while bytes/sec doubles — reply
serialization and socket writes are IO-thread work, so it stops being worker-bound (consistent with
[[thredis-threadcfg-sendbound]]). At p1, 100 members peaks io5/ex3 ~ io4/ex4, and 1000 members is a
flat plateau io5..io2 within 2.9%. So "ZRANGE is worker-bound" is true only for MID-WEIGHT replies at
high pipeline depth. Never quote a single ZRANGE target; state the reply size and pipeline with it.

**Two controller defects found in passing, independent of any mode:** (1) the occupancy EWMA
`s += (int)(ALPHA*(occ-s))` truncates to 0 once |occ-s|<4, so u_ex can never exceed 0.97 — a natural
`u_ex >= 1.0` test compiles, runs and never fires, and every occupancy reading carries a +-3-unit
dead zone; (2) QCAP never doubles off 2048.
Related: [[thredis-bloom-signature-saturation]], [[thredis-flip-pool-broken-p0]],
[[thredis-flip-controller-frozen]], [[thredis-sanity-gate-benching]].
