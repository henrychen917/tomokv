---
name: thredis-flip-anchor-freeze
description: "SHIP-BLOCKER — the self-centring anchor makes |lr-anchor| collapse to 0, killing the flip trigger while the floor test still screams imbalance; controller freezes wherever the ratio stabilises"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-08-09. The most important flip finding. Proven from the controller's OWN log, not inferred.**

# The evidence

`flipauto_no_mget8_p1_m0_r1_FAIL.log`, workload MGET-8 p1, booted io2/ex6, optimum io6/ex2:

    [flip-ctl n0] HOLD 1721286 ops/s io_sat=0.97 ex_sat=0.40 r=2.42 anchor=2.42
                  band=3% floor=1.33 io=3

The trigger is `|lr| > gfloor` **AND** `|lr - anchor| > band`.
- FLOOR test: r=2.42 vs floor=1.33 -> **passes by 2.4x**. The controller KNOWS it is badly imbalanced.
- BAND test: anchor=2.42, so `|r - anchor| = 0` against a 3% band -> **fails**.

It then held that config for the rest of the run at **-30.9%** throughput, fully aware of the
imbalance. Same signature on mset8_p1 (settle NEVER, -12.5%) and zrange_p1 (-4.6%).

# The mechanism

`lr_anchor` is a SELF-CENTRING RUNNING MEAN over settled ticks (server.c, "SELF-CENTRING ANCHOR").
So the moment the ratio stops changing, the anchor slides onto it, `|lr - anchor| -> 0`, and the
trigger dies **no matter how far r is from balance**.

> **The controller only makes progress while the ratio is still MOVING. Once it stabilises anywhere,
> it freezes there and calls it done. It is not seeking the optimum -- it is seeking A STABLE RATIO,
> and every config is stable if you sit on it.**

Why get_p1 still works: `u_ex` swings 0.034 -> 0.593 across the sweep, so r moves faster than the
anchor can track and the band test keeps passing. Multi-key p1 stalls early, the anchor catches up,
trigger dies -- from EITHER direction, which is why all failures converge on io4/ex4.

# Why every earlier flip verdict missed it

The old 3-cell matrix used GET/SET p32 + ZRANGE p32, where balanced saturation IS the optimum
(io4/ex4). A frozen controller passes those trivially. Only workloads where **balance != optimum**
expose it -- MGET-8/MSET-8/ZRANGE at p1 -- and none had ever been tested. See
[[thredis-vacuous-validation-trap]].

# Consequences

1. **The signal question was the wrong question.** m0 / m3 / m5 all share this gate. m0 fails 3/15,
   m3 fails 3/12, on the SAME cells. Fixing `u_io` while the anchor freezes the trigger changes
   nothing. Supersedes the framing in [[thredis-flip-signal-quantity-mismatch]] -- that diagnosis
   is still correct, it just is not the binding constraint.
2. **m5 is still worth having** for a different reason: on mget8_p1 the corrected signal's ONLY
   deadzone across the whole sweep is io6/ex2 = the true optimum, so with the anchor fixed it would
   stop in the right place. The legacy signal has no such property.
3. **This is the owner's "no learned behaviour" condition failing.** The anchor IS learned state and
   here it does not merely bias adaptation, it ends it. See [[thredis-flip-no-machine-constants]]
   for the separate settle-time-scales-with-core-count defect.

# THE OWNER'S SPEC (decided 2026-08-09) — implement exactly this

The owner's framing makes this a BUG, not a redesign: **"anchor never exceeds floor by definition."**
An anchor of 2.42 against a floor of 1.33 is an ILLEGAL STATE.

**ANCHOR** — a LOCAL learned optimum, valid only while the workload is unchanged:
- CAPTURE only while `|lr_ewma| < gfloor`. That alone makes the invariant true by construction.
- DROP (clear, re-seek) when EITHER: `|lr_ewma| >= gfloor` (ratio left the floor), OR
  `|u_io - u_io_at_capture| > 2*sigma_io` / `|u_ex - u_ex_at_capture| > 2*sigma_ex` (magnitude shift
  that leaves the RATIO unchanged — floor-exit alone cannot see it). sigma = MEASURED per-role noise,
  reusing the existing EWMA mean+variance estimator. No new constant.

**BEST_RATE** — reset on ANY ACCEPTED CONFIG CHANGE (a baseline measured at a different split is not
comparable). Stricter and more frequent than the anchor rule; keep them separate. This also fixes
the known never-re-baselines bug.

**FLOOR is the only sanctioned quasi-constant**, and it is already derived from core count.

# WHY THE FLOOR DESIGN IS RIGHT — verified against the measured static curve

`gfloor = gstep/2`, `gstep = ln((ni+1)/ni) + (ne>1 ? ln(ne/(ne-1)) : 1.0)`. Computed per config
against the real sweep, the floor admits only **1-2 configs** per workload (tighter than the owner's
"all but 3"), and the admitted set ALWAYS contains a config at or within 2% of the true optimum:

    get_p1     admits io7/ex1              = exact optimum (the ne==1 branch widens floor to 0.567,
                                             which is what lets it settle at the edge)
    mget8_p1   admits io6/ex2              = exact optimum
    mset8_p1   admits io6/ex2              = -1.9% off optimum, inside the 3% band
    zrange_p1  admits io5/ex3 + io6/ex2    = correct pair; throughput picks between them

So: **the FLOOR narrows, the THROUGHPUT JUDGE picks among survivors.** The band must never veto a
move the floor is asking for.

# THIS IS ALSO THE DECISIVE ARGUMENT FOR THE CORRECTED u_io

mget8_p1 at io7/ex1 (true value 301,570 vs optimum 650,839):
- corrected `u_io`=0.42: `|lr| = 0.865` vs floor 0.567 -> OUTSIDE, correctly rejected
- legacy `u_io` pinned ~0.97: `|ln(0.97/0.998)| = 0.028` vs 0.567 -> INSIDE, wrongly admitted at -54%

The legacy signal does not merely steer slowly — it CERTIFIES a catastrophic config as balanced. The
floor design REQUIRES an honest u_io to work. See [[thredis-flip-signal-quantity-mismatch]].


# FULL 90-CELL CONFIRMATION (flipauto phase 2a, 2026-08-09)

15 workloads x 3 modes x 2 reps, each booted from that workload's MEASURED WORST config, graded
against the measured static curve (PASS = landed within 3% of that workload's best):

    m0  21/30 landings   auto tax -20.2%
    m5  20/30            -21.3%
    m3  18/30            -26.2%

**All three modes are statistically indistinguishable and all fail ~1/3 of workloads.** The signal
question was never the binding one.

Failure structure, and it is uniform:
- `mget8_p1` fails **6/6** — every mode, every rep. Boot io2/ex6, all land io4/ex4, target io6/ex2,
  -28 to -31%.
- Every p32 MULTI-KEY cell booted at io7/ex1 lands io6/ex2 with **settle ~= 10s** and freezes at
  **-39 to -47%** (mget8_p32, mset8_p32, mixms_p32; all modes). One directed step costs ~6s, so those
  runs made **exactly ONE move and stopped** — the anchor captured immediately after the first flip.
- m3 is outright INERT on zrange_p1 and mset8_p1 from io7/ex1: landed == boot, settle 6s, ZERO moves,
  -40 to -43%.

CAVEAT ON THE -20% AUTO TAX: the window includes a 24-42s convergence, so it conflates "took too long
to arrive" with "costs something once there". flipaccept.sh measures POST-SETTLE only and separates
them. Do not quote -20% as a steady-state cost until that lands.

NARROW BUT REAL VALUE OF THE CORRECTED SIGNAL (m5), on the FLOOR test not the band: at mget8_p1 /
io7/ex1 the legacy u_io gives |lr| = |ln(0.97/0.998)| = 0.028 against a floor of 0.567 -> it CERTIFIES
a -54% config as balanced. The corrected u_io gives 0.865 -> correctly rejected. The owner's floor
design requires an honest u_io. But with the anchor freezing after one move, no signal rescues it.
