---
name: thredis-sweep-abandon-livelock
description: "Floor-sweep ABANDON livelock root-caused: capacity predictor fed CAPPED sats misreads the sweep's own move as workload change; law = a signal the actuator moves cannot police the actuator; 3-part fix (abandon-free enumeration, ratification hysteresis, finish re-base)"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-08-09, owner-equation battery on 2s-flip-final.** The battery's failures were ALL one
mechanism, proven from the controller's own log — NOT the owner equation (its cells were clean:
triad CLIMB/FALL 4/4, get_p1 anystart 6/6 chg=0).

# The livelock (get_p32 anystart 0/6 stable, chg 4–9, one cell settle=NEVER −26%)

    ABANDON #8  floor-exit visited=1/3 entry=io6 current=io5 return=io6 lr_equiv=-0.570
    ABANDON-RETURNED intended=io6 actual=io6; re-arm after a fresh settle
    ABANDON #9 ... #10 ... #11 ... #12 ...          (every ~6s, forever)

Cycle: settle → sweep arms → move to first candidate → during-enumeration "workload changed"
floor-exit test compares lr measured at the candidate vs a `tmFlipPredictedLr` capacity
prediction → predictor off by ~0.5 nats > gfloor → abandon → return-to-entry (return path
WORKS) → ABANDON-RETURNED re-arms → sweep again → same physics. chg=4–9 per window.

# WHY the predictor is structurally wrong under the owner equation

`tmFlipPredictedLr` telescopes ln-capacity terms from the ENTRY's measured sats. The owner
equation CAPS u_io/u_ex at 1, so at a saturated entry the cap HIDES demand (u_ex=1 masking
~1.4): predicted u_ex' after +1 EX = 0.67, measured = 0.93 → 0.33-nat spurious deviation on one
side alone. The cap is RIGHT for the trigger ratio and WRONG as a predictor input. Related:
[[thredis-wrong-two-quantities]] — the two operands were "lr predicted from capped entry" vs
"lr measured at candidate".

# THE LAW (second independent instance in this file's history)

**A signal the actuator moves cannot police the actuator. Only throughput can end/veto an
actuation episode.** server.c already records the first instance (climb "premise gone" ratio
test, tried 2026-08-04, REVERTED — landed io6/io3, flips 41→7). The sweep's floor-exit abandon
was the same defect wearing a translation layer.

# The r2-HOLD face of it: raw-argmax ratification

`improved = after > prior_best` (no band) let a +1.1% within-noise reading at io3 displace the
io4 incumbent → HOLD@io4 landed io3 (near-tie curve top, box noise ~2%
[[thredis-box-noise-truth]]). Ties must keep the incumbent.

# The post-KEEP churn face (mget8_p1: right config at 10s, then chg=5)

After a KEEP at a neighbour, the post-completion EPISODE-DROP test still translated from the
OLD entry through the same broken predictor → spurious drop → re-arm → churn.

# THE FIX — five layers, each convicted by its own log before fixing (flipfinal)

1. fca32d2b8 **Enumeration/positioning is abandon-free** except RATE-based tests (idle,
   after<=0, FLIP_LOAD_SHIFT). Bounded loss: frozen candidate set, one excursion.
2. fca32d2b8 **Ratification hysteresis**: displacing standing best requires `after > best +
   band` (2σ/2%, existing machinery); a config may refresh its OWN measurement band-free.
3. fca32d2b8 **Finish re-base**: entry_{io,ex,lr,gfloor} re-based onto the FINISHED split →
   post-completion tests compare same-split quantities only.
4. 16a819793 **Drops need sustained evidence**: floor-drop = FLIP_SUSTAIN Schmitt
   (floor_out_run, settled ticks only — get_p32@io4 sits at 94% of floor and single-sample
   jitter re-armed sweeps every 14s); sat-drop judged in RATE with the sweep's own
   fmax(2σ,2%) band vs rate-at-capture (cap pins u_io 0.985 → σ_u 0.0009-0.0014 → 2σ_u=±0.3%
   read drift as change). OWNER-SPEC DEVIATION: spec said 2σ_u; rate-band is strictly closer
   to "throughput judges" — flagged for review.
5. 6e63178ba **Same-verdict re-verification damping**: this box's p32 cells warm +2.8%/15s
   indefinitely, so even a correct 2% rate band re-fires forever. Consecutive clean-REVERT
   finishes at the same split double the sat-drop band (climb same-wave precedent, shift cap
   3); KEEP/floor-drop/different-split resets. Escape lanes for real change: lr moves (floor
   arm undamped), rate smashes the widened band, or the re-verify returns KEEP.

Harness truths fixed alongside: settle latch 3→5 polls (a 5-7s sweep visit could latch
"settled" mid-transit), landing = stable-config read not one sample (r1 HOLD "landed io3" was
sweep #1's io3 VISIT at T+51s; the cell finished REVERT io4 five seconds after the poll).

Validated per-layer: HOLD probe ×2 on 6e63178ba = one boot-episode sweep each (REVERT damp=1),
zero drops/sweeps after, final io4, ops 7.38/7.40M = +11% over the flicker build.

# Pool-loss RESOLVED as a harness bug (2026-08-09, supersedes my abandon-storm hypothesis)

The ABAB "pool=5/5" was never a server loss and never abandon-related: flipaccept's
`local io=$1 ex=$((8-io))` expanded against the caller's GLOBAL io (=7 after the anystart
loop), so the probe block's `boot 4` requested ex=1 — a 5-thread server BY REQUEST, every run.
poolrepro.sh "passed" because it passed literal `--tomokv-thread-ex 4`, so it never tested the
same thing; its 26 clean polls were true but answered a different question. My "the abandon
storm was evidently the trigger" was WRONG — nothing server-side to fix. Details + proof
one-liner in [[thredis-flip-pool-broken-p0]] (whose guard-firing atomic+auto loss remains a
REAL open P0 — configured-total in the guard line is the discriminator). The in-vivo probe
observations stand: get_p1 climbed io4→io7 and held; get_p32 walked io7→io6→io5 and sat.

# Harness note

The `flips` column counts trigger actuations only; sweep TARGET moves don't increment it —
`landed != boot` with `flips=0` means the SWEEP moved it. `chg` (post-settle config changes) is
the sweep-health column. Also: satharvest.log is APPEND-mode across runs — grep the tail by
current timestamps, or you forensically analyze a DIFFERENT binary's behavior (nearly happened;
old m5 lines lack the `return=` field the current abandon logger prints).
