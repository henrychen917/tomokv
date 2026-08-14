---
name: thredis-flip-test-window-and-drift
description: "Two things that make flip-controller A/Bs lie: a generous measurement window hides the defect entirely, and this box is BIMODAL on the ramp test (same binary 3/4 then 0/4) so only interleaved A/B/A/B is valid"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-05. Building a repro for the flip controller's start-transient bug, two harness properties
each independently produced a wrong conclusion.

## 1. The measurement WINDOW is the discriminator, not the workload

controller_sweep's OPPOSITE-OPTIMUM uses `T_MEAS=20s`. My first repro used 90s with the same
workload and boot config — and the BROKEN binary PASSED, because the controller wanders and then
recovers: measured trajectory `4>5>6>5>4`, landing on the right config with time to spare. At 20s
there is no time to walk back and it ends on io6 at 4.2M against io4's 7.0M.

So a defect that is real, reproducible and costly was completely invisible at 90s. **When
mirroring a failing cell, copy its window and its load-shape step (here: a 1:1 fill at 32 conns /
pipeline 8 followed by 1:0 at 200 conns / pipeline 32), not just its workload.** A generous test
is not a conservative test — it is a test that cannot fail.

## 2. This box is BIMODAL on that test — interleave or the numbers are noise

The SAME binary, minutes apart on an otherwise idle box:
    redis-ramp-PREFIX   3/4 PASS   then   0/4 PASS
    RQUIET(committed)  10/14 PASS  then   5/14 PASS
Sequential arms are therefore NOT comparable, and "arm A scored better than arm B" across two runs
measures drift. Only A/B/A/B interleaving WITHIN one run is valid. The interleaved result was
unambiguous where the sequential one was not:
    BASE 2/14 vs RQUIET 10/14, discordant pairs 9:1, McNemar exact p ~ 0.02.

This is stronger than the general ±2% drift in [[thredis-box-noise-truth]]: the flip test's outcome
is a discrete pass/fail on a marginal race, so drift flips whole outcomes rather than shifting a
number. Report the discordant-pair count, not just the two rates.

## Harness note

`$JOB/uring_test/ab_ramp.sh` does the interleaving; `rampstart.sh` is the single-rep cell (honours
`BIN_OVERRIDE` and `MEAS`). Always run the PRE-FIX binary as one arm — a test that cannot fail
proves nothing ([[thredis-vacuous-validation-trap]]).

Related: [[thredis-wrong-two-quantities]], [[thredis-ab-harness-traps]],
[[thredis-selfmatch-and-lock-traps]].
