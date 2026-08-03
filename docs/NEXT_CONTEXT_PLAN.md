# Plan for the next context — 2026-08-02

Tip: `4bab6353f` on `origin/2s-numa-stable-dev`. FULL bigstress green
(`PASS=28 FAIL=0 INCONCLUSIVE=1 SKIP=0 NA=12`), all four reference cells above baseline.

---

## 1. State

**Done and pushed this session.** J1–J6 defect sweep (2 real fixes, 2 confirmations, 1 reporting
artifact, 1 retraction of my own bad filing); `stress_validation` (~2 h single-server soak);
bigstress made honest (`NA` class, `--dir` hardening, flip tolerance above the noise floor, median
baseline ratchet); ABCD **A1/A2/A3** complete and gated; **B measured and answered**.

**Queued, in this order and for a reason.**

| # | work | why this order |
|---|---|---|
| 65 | ABCD — C and D remain | see §3 |
| 66 | threadcap | rewrites the same `uint64` mask A2 built |
| 67 | per-node semi-main driver | changes who drives the ticks the other two depend on |

---

## 2. The finding that should steer everything

**The worker is overhead-bound, not memory-bound.**

* Per-worker throughput is **~2.0 M ops/s in every thread config** (1.95 / 2.09 / 2.04 M at
  io4/ex4, io5/ex3, io6/ex2) — so the workers are the ceiling, and starving them does not change
  what the ceiling is *made of*.
* A **21× dataset increase costs 3.5%** (243 MB → 5.14 GB; 7.6× L3 → 160× L3). Memory-bound
  workloads collapse. This does not.

⇒ the limit is **fixed per-command work**, not cache misses. That single fact is why prefetch is a
wash and why the next allocation change is currently a guess.

---

## 3. C and D — what changed

**C (IO prefetch): expect nothing, and say so up front.** It measured **−3.9% p32 GET** historically
and ships OFF. B just showed the machine is not memory-stalled, so the same reasoning applies on the
IO side. Build it to spec behind its level, prove engagement, measure, and **do not tune it until it
looks good** — if it is negative here, that is the result. Its value is on multi-CCD.

**D is now the interesting half of ABCD**, because D is about *scheduling* per-command work rather
than hiding memory latency, which is the constraint that actually exists. Design is written in
`docs/ABCD_D_DESIGN.md`: IO owns classification/admission/SEDA window, EX owns readiness and aging;
cross-client reordering justified by the reply-mediation argument; same-key order made structural
via stable partition by target worker; controller built on the `lb_grp_ops` idiom (one relaxed load
per *batch* on the hot path, 1 Hz main-thread tick, level 0 allocates nothing).

**Measure D on the tail, not on throughput.** `tools/preflight/tail_mix.sh`, per-command-class
p50/p99/p99.9 **plus the long-request maximum** — improving short-request p99 by starving long
requests is not a win, which is what D5's aging exists to prevent. Report worst-observed age.

---

## 4. The allocation question, answered honestly

**More is already landed than the task list suggests** (verified in-tree, not from memory):

* `embed192` is **live** — `kvobjEmbedStringFits` is `size <= 192u && len <= 255`
* retire-node `zmalloc` removal (+2.6% SET)
* csGroup inline/SSO (−5.2% instr/op on mget4)

**Disproven — do not re-litigate:** per-command arena (**−18.4% p32 GET**), operand pool
(net-negative, deleted), kvobj pool, per-type pools, cross-thread alloc ownership (~0.3% ceiling).

**So the gap is not an idea, it is a measurement.** The worker spends ~**500 ns per command**
(1 / 2.0 M) and nobody has decomposed it. Allocation is *one* term; fake-client setup, dispatch
bookkeeping, reply construction and the command proc are the others, and their relative weights are
unknown.

**Do this first (task #36's census step, widened beyond allocation):** `perf record` a worker at
io5/ex3 p32 and attribute that 500 ns across those five buckets. Two guesses have already cost
−18.4% and a deleted subsystem; a third guess is not warranted when the census is a day's work and
tells you whether allocation is 5% or 40% of the budget.

---

## 5. Standing measurement rules learned the hard way

1. **Quote engagement next to every number.** A prefetch result without `issued` is meaningless — the
   residency gate is **exactly 100% shut at 2M × 32 B**, the standard apparatus, so every historical
   prefetch verdict measured *disabled machinery*.
2. **Gate-open regimes for prefetch:** ≥8 M × 32 B or ≥512 B values. Never 2M × 32 B.
3. **`io5/ex3 p32` is the standing EX-side cell** (owner ruling) — ~20% lower throughput
   concentrates load on fewer workers, so a real EX regression shows proportionally larger.
   It does **not** manufacture a memory bottleneck the workload lacks.
4. **Pair on one server with the knob flipped live** where the knob is `MODIFIABLE_CONFIG` — removes
   seed-to-seed and build-to-build variance entirely. Report every pair and the spread; if the
   spread exceeds the effect, say inconclusive.
5. **Sanity-check before believing.** A −50% GET with an unchanged SET on the same engine was an
   artifact, not a regression; three other measurements disagreed with it.
6. **Process identification:** `pgrep -x` matches the *command name* (`bash`), `pgrep -f`
   self-matches your own shell, `timeout cmd &` captures **timeout's** pid, and `grep -c … || echo 0`
   emits `0\n0`. Trust the **listening port** and the **withbox parent pid**. Four separate incidents
   this session.

---

## 6. Open, not forgotten

* **J3/J6** — `DEBUG RELOAD` is safe for the server but not transparent; memtier cannot retry
  `-LOADING` and hangs. Server-side is correct.
* **A3's gap** — the back-pressure path is unexercised by any gate (`tomokv_ex_queue_full` stayed 0
  in all cells). Fix with a saturation case: all connections, max pipeline, **one key**, asserting
  `ex_queue_full > 0` so it cannot pass vacuously.
* **`queues[]` is 33 entries while workers take `iotid ≥ 33`** — safe today because every call site
  is IO-side, but it is an unasserted invariant. Add the assert.
* **`SURFACE-GATE`** — the one remaining INCONCLUSIVE; needs an explicit `SURFACE_BASE`.
* **`stress_validation` has never completed a full 2 h run.** Three attempts, all stopped by my own
  harness bugs (SCAN guard, reload-vs-oracle contradiction, BUSY retry) — all fixed, none re-run to
  completion. **Run it once, green, before trusting it as the ABCD gate.**
