---
name: thredis-flip-signal-quantity-mismatch
description: "Flip's r=io_sat/ex_sat divided a zero-event-pass proxy by a true-idle measure; corrected u_io is reproducible +-0.005 but does NOT beat m0 at steady state"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-09. Validating flip signal modes on `2s-flip-iowait` @e566c3f4f (modes 0/3/5 in ONE binary,
so no cross-binary confound).

# The root defect

`r = io_sat/ex_sat` has been dividing **two different kinds of quantity** since it was written:

| operand | source | what it measures |
|---|---|---|
| `u_ex` | worker `tm_idle_us` (server.c:20815, 20865; read 23579) | TRUE idle time — episode opens on empty queue, closes on pop |
| `u_io` | IO `tm_idle_us` (server.c:21633) | wall us in ZERO-EVENT PASSES — a pass with one event counts fully busy |

This is the [[thredis-wrong-two-quantities]] class sitting in the controller's central ratio. It
explains BOTH symptoms at once: why `u_io` pins near 0.97 (under load almost no pass is event-free),
and why the bias always pointed toward GROWING IO (the IO side systematically overstates busy).

Mode 5 substitutes `u_io = EWMA(1 - epoll_wait/wall)` in double. Measured, same io4/ex4 config:

    SET p32     u_io = 0.988 / 0.983 / 0.988   (IO genuinely saturated; optimum IS io4/ex4)
    ZRANGE p32  u_io = 0.730 / 0.735            (IO not the bottleneck; optimum is io2/ex6)
    legacy      ~0.97 for BOTH

Reproducible to **+-0.005**, separating the two workloads by 0.25. A genuinely good signal.

# But it does NOT win at steady state

Two reps, three cells (means):

    cell         m0        m3        m5
    SET p32      6175218   6217876   6275850   (m5 +1.6% vs m0)
    ZRANGE p32    719670    702198*   718497   (m0 vs m5 = 0.16%)
    crossover     406674    410800    400407

Every m0-vs-m5 gap is inside this box's +-2%. Reason: the ratio only TRIGGERS exploration; the
**throughput hill-climb** does the optimizing and REPAIRS a wrong first move before it reaches the
landing. A better input is invisible when the judge cleans up after the bad guess. The code knows
this — "Nearness to 1 does not make a config good... Throughput still picks among them."

TRAP I FELL INTO: from rep 1 I concluded "m5 goes the right way first try, m0 wastes an excursion,
+2.2%". Rep 2 killed it — m0 also hit GF=0, and m5 wasted one. Excursion count is symmetric noise.
One rep is not a result on this box (see [[thredis-flip-test-window-and-drift]]).

ALSO CORRECTED: I had been carrying "m0 beats m3 by 6.5% on ZRANGE p32". Real figure is **0.6%**.
The 6.5% came from a STATIC reference curve (780,879 vs 744,989); both auto arms sit 5-9% below
their static references, so the gap washes out. Always compare auto-to-auto.

# The SET p32 conformance cell is VACUOUS — and so were the old ones

8 reps x 3 modes on SET p32: **24/24 PASS for every mode**, and the controller's own HOLD line says
why — `GB=0 GF=0` in all 24, `r = 0.94-1.06` against a floor of 1.33 (m0/m5) / 1.15 (m3). It never
triggers. And the harness booted at io4/ex4, which **IS** that workload's optimum.

So the cell is passed by a controller that does *literally nothing*. It never tested the mechanism.
This is [[thredis-vacuous-validation-trap]] again: the gate never opened.

CONSEQUENCE: any conformance cell whose BOOT config equals its TARGET config proves nothing. Of the
three cells in the m3way matrix only ZRANGE p32 (boot io4/ex4 -> target io2/ex6) and the crossover
required movement; the SET p32 rows were decoration. The historical "m0 fails SET p32 1 run in 4"
almost certainly came from a run that started somewhere else.

FIX ADOPTED: conformance cells now BOOT FROM THE MEASURED WORST config for that workload, so the
mechanism must find its way, and the table prints boot alongside landed so a boot==landed==best cell
is visible at a glance. Also: only workloads whose static curve spread exceeds ~5% get a pass/fail
at all — on a flat curve every landing is worth the same throughput and a verdict there is noise.

# Verdict and what to do

m3 (pure worker idleness, the owner's "get rid of io side signals" idea) is **REFUTED, 0/2**, with a
mechanism: under CLOSED-LOOP load arrivals are gated by completions, so workers never saturate even
when adding workers would raise throughput. A worker-only signal sees worker SATURATION but never
worker USEFULNESS, so at a near-balanced config it has no trigger (GB=0 GF=0). It does fire from a
lopsided start (io7/ex1), so the blind spot is precisely the steady state.

Take the corrected `u_io` for CORRECTNESS, not throughput — and because it is the only route to
fixing uring, where the signal is actively broken (`io_sat 0.17` on a 99.5%-CPU thread), not merely
imprecise. Under [[user-hardcode-or-delete]] it should REPLACE `u_io_idle` as the controller input,
not ship as an opt-in mode 5.

RESIDUAL, NOT FIXED: `u_ex` is still an INTEGER EWMA that truncates and caps at 0.97, so m5 pairs an
unbiased `u_io` against a biased `u_ex` — at true balance `ln(1.00/0.97) = +0.030`, a standing tilt
toward growing IO (~12% of the 0.255 floor). The code's "anchor cancels it" argument covers the BAND
test (a difference) but NOT the FLOOR test (absolute against r=1). See task #114.
