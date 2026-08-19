# flip u1 — the universal controller

Owner mandate 2026-08-19: *"I want a universal flip controller that can adapt to any workload
and any hardware and any server config."* This supersedes the r-series signal patching and the
2026-08-15 economics freeze (owner opened the door; this closes the series).

## Why r1..r9 can never be universal

Every r-series signal is a PROXY: occupancy, work density, cpu saturation, and their ratio
r = u_io/u_ex. The controller rests where the proxy says "balanced" (r inside anchor±band).
Turning a proxy equilibrium into a throughput optimum requires a MODEL of the machine and the
workload — and that model is exactly what changes under our feet:

* EX workers are work-bound (~2M ops/s/worker measured ceiling). When ex paces the pipeline,
  ex occupancy reads ~busy NO MATTER whether an extra ex thread would buy anything. The
  occupancy balance point is therefore biased ex-ward of the throughput optimum whenever ex is
  the paced stage.
* Measured on the 2026-08-19 gate (16c nodes): get_p16 searched and RETURNED to the boot split
  io8/ex8 (its proxy equilibrium) leaving 38% on the table at io11/ex5; set_p1 climbed
  correctly but stopped one step past the peak (r crosses 1 above the peak on the io axis);
  mget8 never armed at all. Three signatures, one defect: proxy equilibrium ≠ objective optimum.
* The same controller "worked" on the 8c box because the two points coincided at that scale.
  That is the definition of a machine-specific constant hiding in a signal.

Conclusion: no proxy signal is universal. The only quantity that is true on any workload, any
hardware, and any config is the objective itself: measured steady-state throughput at a held
shape. u1 optimizes that, directly.

## Principle

u1 is an online, noise-aware hill-climber on the shape lattice. Proxies are demoted to two
non-authoritative jobs: (a) ordering probe directions (a prior, not a veto), and (b) cheap
post-convergence change detection. Neither can block or force a move; only measured throughput
comparisons do.

The controller becomes the same instrument we already trust to judge it: the flip_landing
suite lands, then probes neighbors, then compares. u1 internalizes that method.

## Architecture (per node)

Shape lattice: (io, ex) with io+ex = N for 2s; (io, ex, wb) summing to N for 3s. Neighbor =
one ±1 exchange between a role pair. Nothing in the loop names a role: K roles = K·(K−1)
exchange directions. This is what makes 3s and any future role a config change, not a
controller change.

### 1. MEASURE
Per-tick (existing 4Hz cadence) per-node ops deltas, aggregated into sub-windows. Two same-
shape adjacent sub-windows feed a running A/A noise estimator σ (per era). σ is measured on
THIS box under THIS workload right now — the universality anchor. Every threshold below is
expressed in units of σ; there are no absolute numbers.

### 2. SETTLE
After any role conversion, discard ticks until the short-bin ops slope sits inside the noise
band. Settle time is DETECTED, never assumed — hardware differences (conn rebalance cost,
cache warmup) are absorbed here.

### 3. COMPARE
Candidate vs current = interleaved paired sub-windows (A/B/A/B…), sign test on the pairs.
Interleaving bounds loadgen drift (banked law: 20s exposes what 90s hides; discordant pairs
decide). Adaptive pair count: stop early when significant, declare FLAT at the cap. FLAT or
LOSS ⇒ revert and mark the direction exhausted; WIN ⇒ keep, direction stays live.

### 4. CLIMB
Probe directions ordered by the proxy prior (they usually point right mid-gradient; they are
just wrong near optima — exactly where the measurement takes over). Momentum: two consecutive
wins in one direction double the step, first loss halves it back to 1 (distance-derived, no
machine constants — owner rule). A step whose measurement loses reverts atomically. Search
terminates when every direction is exhausted at step 1 ⇒ ANCHORED.

### 5. QUIET (owner thrash definition)
Anchored ⇒ zero moves. No background probing, no curiosity moves. The movelog verdict for an
anchored era must be STABILIZED_CLEAN with post_stable_moves=0, always.

### 6. WATCH (re-arm on change, ≤3% law)
Post-anchor, a watchdog compares the era signature — command-mix histogram, offered-load
level, per-role occupancy vector (counters that already exist) — against its anchor-time
snapshot, with drift judged in σ-of-signature units. Sustained drift ⇒ new search episode.
The watchdog reads INPUTS, never the objective, and only runs while the actuator is idle;
the sweep-abandon LAW (a signal the actuator moves can't police the actuator) is satisfied
by that timeline separation. Steady-state cost is a handful of counter reads at 4Hz.

### 7. COORDINATE (multi-node)
A probe token rotates across nodes: only the token holder probes; the others hold shape, so a
probe's measurement is never contaminated by a concurrent probe (one-server-one-bench, applied
inside the server). Per-node optima may differ (per-node control plane); all-anchored ⇒ the
box is quiet.

### 8. IDLE
Ops indistinguishable from zero (vs σ) ⇒ park, keep the last anchor, wait for load. The mget8
failure class (never arming) is structurally impossible: a fresh era ALWAYS searches; there is
no demand gate with authority to hold the search closed.

## Universality checklist

* No absolute thresholds: every decision in units of measured σ (A/A) — adapts to box noise
  (7700X ±2%, EPYC ±0.15%, future NIC jitter).
* No role semantics in the loop: 2s/3s/any lattice from config.
* No workload model: MGET fan-out, atomics ON/OFF ratios, value sizes, mixed pipelines are all
  absorbed by measuring the objective.
* No hardware model: settle detected, noise measured, step sizes distance-derived, node count
  from topology.
* Boot split irrelevant: search starts unconditionally; a bad boot shape costs search time,
  not the destination.

## What u1 must beat (acceptance)

1. flip_landing, 16c standard, ALL 11 cells ≥0.95× discovered best — the KNOWN-LIMIT branch
   gets DELETED from the suite the day u1 passes it.
2. Universality proofs, same binary, zero retuning:
   a. 8c-node geometry run (different hardware shape),
   b. atomic-ON workloads (the r-series blind spot; io6/ex10-class optima),
   c. workload-switch chain (get_p16 → set_p1 → mget8 live transitions; re-arm, re-land,
      thrash-clean between),
   d. 3s lattice (io/ex/wb) once the climber is proven on 2s.
3. Search cost reported per era (movelog: moves + span); steady state zero moves.
4. Pre/post table vs r8 on every cell (owner rule).

## Build plan

* u1a substrate (codex round, passive alongside r8): per-node windowed ops, A/A σ estimator,
  settle detector, paired-comparison engine, DEBUG TOMO-U1TRACE firehose. No behavior change.
* u1b climber (2s): mode `tomokv-thread-mode universal` — full loop on one node, then token
  coordination. A/B vs r8 (mode flag on the same binary).
* u1c watchdog + era signatures + re-arm.
* u1d 3s lattice + unified-binary integration.

flipdiag (in flight) still pays twice: it confirms the proxy-equilibrium diagnosis with the
r-series' own trace, and its per-rung traces calibrate u1's priors (which way proxies point
mid-gradient) and give first σ/settle figures per workload class.
