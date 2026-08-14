---
name: thredis-forwarding-abandoned
description: Value-forwarding is permanently abandoned — falsified by three independent physics walls; keep only as a paper negative result
metadata:
  type: project
---

Value/value-forwarding (predicting the next consumer of a just-produced value to skip the dict
lookup) is **permanently abandoned** as of 2026-07-08 (user: "give up on forwarding"). It has been
falsified THREE independent ways over the project:

1. **No runs** — the original predictor apparatus (boPredictOne/exPredictForward, deleted in commit
   0d97046a1): real/uniform workloads have same-key run length ≈ 1.008, so a run-predictor has no
   signal. DISABLED default, then deleted.
2. **Lookup isn't the bottleneck** — even with maximal synthetic runs + zero-copy, the saved dict
   lookup is L3-cheap while dispatch dominates; invisible at 32B.
3. **Hot keys have hot dict paths** — the loop-2 L0 worker read-latch (version-guarded, no-UAF;
   patch preserved f1_l0_latch.patch): a latch-hittable key is already L1-resident in the dict, and
   the expensive cold/DRAM lookups are exactly the ones that never repeat. A cache in front of the
   dict cannot beat the hardware caching the dict itself. Bench: extreme-hot -0.22% vs +2% gate.

**Do NOT reattempt on this class of hardware.** The only open door is cross-CCD/multi-CCD (a remote
lookup is genuinely expensive there) — parked on the Threadripper list, low priority. Preserved
patches (f1_l0_latch.patch, f2_coalesce*.patch) in overnight_sweep/selfimprove/ are the negative-
result evidence for the paper. The forwarding dev branch 2s-forwarding2-dev also carries the
ORDER-1 reply-ordering bugfix (b8ac230b4) which IS being merged to canonical — that fix is the one
valuable thing the forwarding investigation produced. See [[thredis-forwarding-deadend]].
