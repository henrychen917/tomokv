---
name: thredis-flip-signal-and-qdepth-truncation
description: "Flip controller 2026-08-03: the EX backlog term had been structurally pinned at 0 by a >>4 truncation (both old and new signals); best_rate never re-baselines and locks the actuator out; owner ruling that the climb-till-overshoot law STAYS"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-03. Three findings on `tomoFlipController`, plus a binding owner ruling.

## 1. The EX backlog term was dead, in BOTH signals (FIXED `0eb1eaa1b`)

`exThread.tm_qdepth_ewma_q4` stores standing backlog **×16** (Q4). The controller read it back as
`tm_qdepth_ewma_q4 >> 4` — an integer divide that **floors any depth below 1.0 to exactly zero**.

So the old `ex_sat = max(busy/75, qd/(8*POP_BATCH))` collapsed to bare `busy/75`, and the new
`S_EX = (C+Q)*U/C` collapsed to `U_EX`, identically. Measured: `q_ex` was 0 in **every** sample at
4.9M ops/s. Nobody had noticed because the utilization term dominates whenever the queue term is
zero, so `ex_sat` still printed a plausible number. **A term pinned at its identity value is
indistinguishable from a term that is merely quiet** — the [[thredis-vacuous-validation-trap]]
pattern, one level down.

Fix reads it as `(double)tm_qdepth_ewma_q4 / 16.0`; `node_idle`'s `qd_max == 0` became `< 1/16`.
Gate verified open: p32 SET reports `q_ex=2.75` (non-integer ⇒ precision genuinely retained).
Still 0 in most p32 samples — workers do keep up there — but the term is now live.

Sub-1 depths are the whole point: under **closed-loop** load (memtier, fixed conns × pipeline)
arrivals are gated by completions, so a bad config does not present as a big queue, it presents as
a persistent *small* one.

## 2. `best_rate` never re-baselines ⇒ permanent actuator lockout (OPEN, task #74)

Per-climb `best_rate` is captured once and never reset on a load change. A climb that starts during
a workload transition latches a peak from the *departing* load (trace: `best 2489228` was the only
distinct value in the whole log while the real rate was ~445k), judges every later step as a
catastrophic regression, spends `FLIP_COAST=1` immediately, declares OVERSHOOT, walks back, and on
ending the climb pins `dz_front = |settle imbalance| * FLIP_DZ_RAISE`. Observed `dz(f1.12)` and
later `dz(f1.36/1.37)` against a steady imbalance of 0.16–0.25 ⇒ **grow-front can never re-fire**.
Last log line showed the server at 5.04M ops/s still holding the config a 2.49M "best" chose.

Explains 3 of the flip cell's failures (`SHIFT-ioward`, `AUTO==STATIC-p1`, `SHIFT-exward`) as ONE
behaviour: auto ends at `io_end=4` below its own `io_boot=5`, so there is no grown slot left for
grow-back to reclaim. Not a harness artifact — any real load shift mid-climb does this.

## 3. OWNER RULING (binding): the climb law STAYS

> "when flip triggers still go all the way then fall back once it overshoots, that part stays the same"

So #74's fix is **only** re-baselining `best_rate` on a load change — NOT replacing the control law.
This **supersedes sections 4 and 6** of `docs/FLIP_SATURATION_SPEC.md` (computed-target
proportional allocation). The spec's surviving value is the SIGNAL in section 3.

## The signal change itself has earned nothing yet (`4f65c1b6a`)

`S_r = (A_r + Q_r) * U_r / C_r`, no new hot-path counter (uses the chain identity `A_IO ≡ C_EX`;
`Q_IO` is the pending-write list, **not** `rob` — rob is `replyWorking`, in flight *on workers*, so
charging it to IO double-counts EX's backlog). A/B vs the old signal was a **complete wash**, 11/11
identical verdicts — because both Q terms were zero and S degenerated to the old utilization.
`q_ex` is now fixed; `q_io=0` is a *workload* property (non-zero only when send-bound), so
**re-run the signal A/B at 16–64KB values before judging it.**

## Cost note

Flip's always-on tax is up to **3 `clock_gettime` per event-loop pass** (`ae.c:646/664/691`, gated
`timing != NULL`); `tmIoBusyBegin` is role-transition only. Static mode returns early everywhere, so
`--tomokv-thread-mode auto` vs `static` at p1 **is** the total tax. If material, SAMPLE U (1 pass in
16, scale) — U is a ratio over a 250ms tick and needs a representative sample, not every pass.
Prefer sampling over event-driven arming: under closed-loop load a bad config sits at equilibrium
with small-but-nonzero backlog, so an arm threshold must be low and would arm nearly always anyway.

Related: [[thredis-vacuous-validation-trap]], [[thredis-flip-controller-momentum]],
[[thredis-lb-3pct-budget]], [[thredis-three-regime-testing]].
