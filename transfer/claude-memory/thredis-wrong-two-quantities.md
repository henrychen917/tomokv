---
name: thredis-wrong-two-quantities
description: "The dominant flip-controller bug class: a gate that compares the wrong two quantities. Four instances in one day, each producing a confident, silent, plausible wrong decision rather than an error"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-04/05. Every controller defect found in a full day of flip-controller work was the same
shape: **a comparison between two quantities that are not the same kind of thing.** None threw an
error. Each produced a plausible number and a confident wrong decision.

## The four

1. **CPU time vs occupancy.** `io_sat` was scheduled CPU. An over-provisioned IO thread does not
   block, it SPINS, so polling an empty socket set counted as work. At p32 SET io6ex2 it read
   `busy 0.913` while genuinely idle 41.3% of the time — the two summed to 1.327, and that overlap
   is the tell. `r` read 0.986, dead on 1, for a config at 57% of peak. Fix: occupancy =
   1 − (measured time with NO WORK AVAILABLE), measured identically on both roles.

2. **Fast signal vs slow signal.** `u_io` was a raw per-tick mean; `u_ex` was an EWMA(0.25). Their
   ratio is not a ratio of utilisations during any transient — on a load step the IO term moves
   first and `r` spikes from filter lag alone. Fixed sign, so it does not average out, and largest
   exactly when the workload changes.

3. **Instantaneous threshold vs noisy signal.** `sat_total >= 0.95` on a signal that swung
   0.94–1.09. The gate flickered, and a CLI-BOUND tick RESETS `lr_out_run`, so one blocked tick in
   eight made a run of 8 unreachable — forever, silently. Fix: filter the gate input like every
   other input. (And the 0.95 itself was calibrated for CPU time and died with fix 1 — changing a
   signal silently invalidates every threshold derived from it.)

4. **Scatter vs trend.** `idle_stable` gated climb-start on `|mean − inst|`, an EWMA against the
   instantaneous rate. That measures SCATTER. On a smooth ramp the EWMA TRACKS the ramp, the gap
   stays small, and the gate opens mid-ramp — low noise plus large trend is exactly the case it
   must block. (The eventual fix was different again: the real trigger was the CONNECTION STORM,
   which precedes the throughput ramp, so a rate-trend detector still guarded the wrong signal.
   Gate on the RATIO's stationarity, because the ratio is what the decision is made from.)

## The rule

Before trusting any gate, name both operands and ask whether they are the same kind of thing,
measured the same way, over the same window. If the decision is made from signal X, X is what must
be tested — not a proxy that correlates with X in steady state.

## Corollary that cost a whole A/B

An EWMA quiet-detector must compare the value BEFORE vs AFTER its update. Comparing `lr_ewma`
against a `prev_tick` assigned from `lr_ewma` at the end of the previous tick is identically zero,
so the counter reads "quiet" forever and the gate never fires. Symptom: the change appears to do
nothing, for a reason unrelated to the theory. Verify a new gate FIRES (log it) before believing
its A/B — same discipline as [[thredis-vacuous-validation-trap]].

Related: [[thredis-flip-controller-momentum]], [[thredis-flip-signal-and-qdepth-truncation]],
[[thredis-uring-busy-accounting-blind]] (the same class: wall-span accounting vs work under
DEFER_TASKRUN).
