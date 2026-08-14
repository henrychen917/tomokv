---
name: thredis-flip-controller-momentum
description: The p32-SET "regression" was the OLD flip-balancer thrash (not the flat table); reworked tomoFlipController to a momentum hill-climb + look-ahead that holds steady at 0 flips
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-07-24 — p32-SET regression + p1 auto-flip fixed by reworking the flip controller (7700X,
memtier, flat default-on, numa=1, io4/ex4 boot, seeded 2M×32B).** Branch 2s-numa-shared-kv-dev,
commit **6f74b33ce** (adversarial re-review in progress before push).

**ROOT CAUSE (measured, interleaved):** the "p32 SET 6M→3.1M" was NOT the flat table. Physical-shard
baseline (paper-baseline e39b355ba, memtier) = **5.2M**; flat-static (thread-modes OFF) = **5.0M
(−3%, flat table nearly free)**. The whole loss was the OLD extremum-seeking flip controller/balancer
THRASHING: flat+balance warmed = 4.6M (−12%, still 4 flips in a 60s window), and the no-warmup sweep
= 3.1M (−40%). README is MEMTIER (user confirmed), memtier p32 SET tops ~5M; the remembered "6M" was
a cooler box / redis-bench.

**STATIC p1 GET CURVE (thread-modes off, warmed 45s, interleaved) — MONOTONIC:**
io4/ex4=**595k**, io5/ex3=**714k**, io6/ex2=**814k**, io7/ex1=**833k**. So io7/ex1 (or io6/ex2) is
the p1 optimum and BEATS the redis/valkey/dragonfly field (~800k). No local min — the climb just has
to reach io7. (Static p32 SET optimum is io4/ex4, the ex-heavy end.)

**NEW CONTROL LAW (user directive: "pick direction by front/back pressure + throughput; keep going
while throughput increases till you overshoot, go back, set the deadzone"):** replaced the z-score
extremum-seeker in `tomoFlipController` with a throughput-gradient hill-climb:
- DIRECTION from io_sat vs ex_sat, SMOOTHED via `imb_ewma` (single-tick spikes can't start/mispin).
  Signals unit-free, normalized to the quorum balancer's bands: io_sat=ing_mean/32 (events/pass),
  ex_sat=max(busy%/75, qd_max/(8·popbatch)); ex busy% from per-worker `tm_busy_us` deltas / a
  PER-NODE wall interval.
- START only when the EWMA mean has CAUGHT UP to the live rate (|mean−inst|<2σ, idle_stable ≥ 5) so
  the first baseline isn't the inflated tail of a workload transition.
- CLIMB: keep flipping the same direction while each step beats the BEST rate this climb. INSTANT-GAIN
  fast path accepts a clear gain without the settle wait (an early DIP may be the cache-cold rebalance
  transient → wait; an early GAIN is unambiguous → take it) — lets the p1→p32 shift ride io7→io4 in
  seconds not ~40s/step.
- LOOK-AHEAD (FLIP_COAST=1): coast up to 1 non-improving step past the best, then walk back to it.
  Crosses a single-config dip — including a FALSE dip from a transient-inflated baseline (see gotcha).
  Bounded to COAST+1 steps ⇒ no ratchet.
- SETTLE: pin BOTH deadzones at |imb_ewma|·1.5, **NO decay** (decay re-probed every ~1.5s). Steady
  workload sits at ZERO flips; a real shift's pressure blows past the pin and re-arms instantly.

**VALIDATED (final build):** p32 SET fresh = 5.09M, **0 flips**, holds io4/ex4 (flat-static parity).
p1 GET = 821k, 3 grow-fronts to io7/ex1 then **0 steady-state flips** (livelock check: 0 flips in a
45s held window). p1→p32 shift rides grow-back io7→io4 (3 steps, instant-gain) to the write-optimal,
no thrash. (Old controller: p1 took ~120s + re-thrashed each cell; p32 thrashed forever.)

**KEY GOTCHA — inflated baseline from the workload's own startup burst:** right after a p32→p1 switch,
p1 io4/ex4 reads ~740k for a few seconds (both mean AND inst) before settling to its true 595k. The
caught-up gate can't tell a stable-but-transient burst from steady state, so the first climb step
(io4→io5=714k real) reads as a "dip" vs the inflated 740k. The LOOK-AHEAD is what saves it: io5 coasts,
io6=814k beats 740k ⇒ resume. Don't chase a "perfect baseline" — coast the false dip instead.

**First adversarial review (9 agents, pre-rework version) found 4, all fixed by the rework:** HIGH
livelock (optimum straddling 2 configs — pinned deadzone+no-decay kills it), MED ratchet (look-ahead
bounds it), LOW fc->backoff monotonic accumulator (abort now ends climb with a FIXED pause), LOW
busy% ~2× inflated on a node skipped by an earlier node's flip (per-node wall interval).

**HARNESS GOTCHA:** never `make` while a benchmark is running from the SAME `src/redis-server` — the
rebuild overwrites the binary mid-run ⇒ 0-ops cells (looks like a wedge; it's a build collision). Also
use an isolated `--dir` (a stray dump.rdb auto-loads ~2M keys and pollutes fresh-boot runs).

**SECOND adversarial review (15 agents, momentum+look-ahead version) found 10, all fixed:** instant-gain
ratchets best_rate off a multi-tick transient (HIGH) → EARLY-MEASURE now sets best_rate from a measured
window not the raw EWMA; walk-back counted aborted flips + wasn't abort-safe (MED×2) → confirm-a-step-
landed-before-counting + walk back to best on a coasted pool-edge; actuation-abort didn't pin +
mid-climb refusal pinned as permanent (MED/LOW) → pin on abort, retry-don't-pin on refusal; global
tm_flip_aborted clear not node-scoped (numa>1) → node-scoped. Dead revert_dir/revert_retry handlers
removed. p1 reproducible 813k×3 boots (io7/ex1, 3 flips, 0 steady).

**PUSHED to origin/2s-numa-shared-kv-dev @4293a3d0c (2026-07-24)** — fast-forward from 4b3731f7a
(flatstore default-flip, already public). Then launched the full competitive README sweep
(comp10h_flat.sh: tomo vs redis/valkey/dragonfly/garnet, numa=1, families p1/p32/dram/hot/nonstd,
600s/cell, ~11h) with the fixed controller. TODO: collect sweep results, update README-NUMA table.
See [[thredis-flip-overhead-decomposed]] and [[thredis-thread-modes-step4-balancer]].
