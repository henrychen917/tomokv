---
name: thredis-flip-shipped
description: "Flip endgame SHIPPED 2026-08-09: dev @b04af268d (merge of 2s-flip-final @9e5897f8c) — owner-equation controller, triad 6/6 first ever; final architecture + acceptance numbers + 3 residuals"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-08-09, owner accepted ("finally yes push that to dev"). Dev @b04af268d on both remotes;
branch 2s-flip-final @9e5897f8c also on GitHub.**

# The shipped controller (the whole algorithm in one paragraph)

`u_io = EWMA(productive IO work µs / wall)`, `u_ex = EWMA(EX busy µs / wall)`, both capped at 1;
`lr = ln(u_io/u_ex)`. TRIGGER: |lr| ≥ gfloor (gstep/2, gstep = ln((ni+1)/ni)+ln(ne/(ne−1)), ne==1
branch widens) sustained FLIP_SUSTAIN=8 ticks (Schmitt). ACTUATION: k-jump, k=max(1,⌊|lr|/gstep⌋).
EPISODE (once per settle): DIRECTIONAL walk — one direction from lr's sign, one step per
significant gain (2σ/2% band), coast crosses one dip, overshoot walks back to best, ties keep the
incumbent. ANCHOR: FROZEN snapshot at capture (fold deleted — a tracking anchor blinds its own
band). DROPS (any → forget + re-verify): floor-exit | anchor-band (|lr−anchor| > 2σ_lr) |
rate-band (|rate−rate_cap| > fmax(2σ,2%)) — each Schmitt-gated, each damped ×2 per consecutive
same-split REVERT (cap ×8; KEEP/floor-drop/other-split resets). JUDGE: getNumCommands() —
client-visible commands (nodes==1); per-worker ops_total counts dispatch GROUPS which scale with
worker count on multi-key and vetoed correct grows (mget8: judge said io4>io5 while memtier said
+18% for the move; the fix recovered +13.7–40%).

# Final acceptance (fresh same-binary census tables, quiet-gated)

Triad 6/6 FIRST EVER (HOLD 2/2 io4 0-flips 7.70/7.76M, CLIMB 2/2, FALL 2/2). get_p1 6/6 chg=0 at
parity. get_p32 5/6 → io4 (io3-boot 8.005M = +0.8% ABOVE static best). mget8 5/6 → io6 ±0.8% of
best. zrange flat-top ties ≤1.5% ops (io7-boot → io2 at +2.8% above best). Probes 4/4 on-the-fly
(io4→io7 14s; io7→io4 on live p1→p32 switch), visit2≡visit1 ≤0.6% = no learning. POOL BROKEN 0.
Strict verdict column: 17 PASS / 3 FAIL / 8 UNSTABLE — the non-PASS decompose to the 3 residuals.

# The 3 residuals (owner knows; none blocking)

**CLOSED-BY-POLICY 2026-08-10**: the controller is frozen (owner rule) and all three residuals are
measurement-protocol items, not product defects — warmup A-B-A is a conformance-harness ordering
refinement, modal-landing is a harness sampling choice, zrange tie policy is a judged-tie
convention. No code change allowed under the freeze; conformance suite runs as-is. Revisit only if
the owner unfreezes the controller.

**Residual 2 RESOLVED 2026-08-11** (owner's mid-move challenge): implemented in controller_sweep
OPPOSITE-OPTIMUM (dev ea7e661ed + 86e05835b) as certified-settle read (40s flip-quiet windows
under sustained stimulus) + MODE of <=3 certified landings. Doing so exposed that the cell's SET
oracle had gone STALE — p32 SET optimum moved io4ex4 -> io5ex3 (+3%, io6ex2 -31%) on stable
@09774330d, the m5 controller was finding the true optimum 3/3 and being graded wrong. Cell
redesigned: SET boots AT optimum io5 must modal-HOLD, GET boots io4 must modal-CLIMB; PASS on
rerun. Controller VINDICATED in both directions — see the composite-verdict section of
[[thredis-session-2026-08-10-close]]. LESSON (now in the cell comment): any conformance cell that
encodes a measured optimum rots as the binary improves; a consistent modal landing one step off
the expectation means re-measure the curve BEFORE blaming the frozen controller.

1. **Warmup-window timing**: a cold episode lands one short (get_p32 io2→io5, −6%) or corrects
   late (chg-flagged). Designed fix: A-B-A entry re-measure inside the episode — if entry moved >
   band since baseline, the comparisons were tide-biased → re-run warm (don't damp).
2. **Harness landing read** can latch a 6-s sweep transit even with 2-consecutive-equal polls
   (mget8 io2 "+107.9%" artifact — physically impossible ops prove it measured elsewhere). Fix:
   modal config over last ~6 polls.
3. **zrange flat top**: live io2/io3/io4 within ~1.5%, table says io2+2.8% — config-exact landing
   there is an owner policy call (throughput ties).

# Merge notes (dev @b04af268d)

csCommitLock = dev's self-drain (deadlock cure) wrapped in tmIoWaitBegin/End (drain billed as
wait — conservative). Stamp-push spin keeps stamp_full counter + wait bracket. Struct-tail + INFO
= unions. Merged-tree verify: notifyguard 11/11, static+auto boots, 30s p32 held io4 @7.37M.

# NEXT (owner's order): prefetch "fetch real thing" + hot-key/recency owner-path, then atomics,
then audit forks. Prefetch state: stages exist, default level 1 = noop; lvl3 = 201M slot+149M
kvobj issues/25s, +0.9% mean, IPC 1.15→1.21-1.26; gate50_lvl3.out has the residency-skip A/B;
skewgate says busiest_share ≈0.25-0.27 (no per-EX hot-key headroom on tested workloads).
Related: [[thredis-sweep-abandon-livelock]], [[thredis-flip-pool-broken-p0]],
[[thredis-prefetch-truth]], [[thredis-flip-anchor-freeze]].
