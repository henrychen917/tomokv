# flip r10 — jump to predicted equilibrium, then measured climb (owner design, 2026-08-19)

Owner: *"bring back the more fine grain approach where still we jump straight to where we
predicted equilibrium to be. then climb in the direction we initially jumped in, if no
throughput improvement then go back if yes then keep climbing. we try both sides of initial
jump spot and climb in direction where better stable throughput is. this makes it take way
longer but no need table or any static numbers."* Both controllers are KEPT: the load-based
one (r8 jump + this climb) and m1 (model mode). Separate SQE/submitter threads are permanently
dead (owner: retested repeatedly, always loses) — nothing here or elsewhere may reintroduce one.

## Shape

PHASE J (jump — r8 unchanged): the full r1..r8 stack runs exactly as today and walks to its
proxy equilibrium J. Its decision code is byte-identical. Reaching the anchor condition (lr
inside band + sustained quiet) enters CLIMB instead of terminal quiet. Flat-gradient cells also
enter when the physical per-node role shape has stayed unchanged under non-idle load for
`2 * max(last u1a settle ticks, TOMO_U1_SUBW_TICKS)` controller ticks; the load floor is the
current mean scaled by u1a's relative sigma. During the final one-quantum half of that span, the
single r8 in-floor-sweep ownership point suppresses a new sweep, and r10 wins the equality tick.
The pre-existing dead-arm route remains the earlier no-demand rescue.

PHASE C (climb — per node, fine-grain single steps, all decisions in sigma units):
  C0 baseline: hold J; wait settle (u1a settle detector); collect paired sub-windows -> T(J).
  C1 first side: step one rung in the direction of r8's LAST move before anchoring ("the
     direction we initially jumped in"); settle; measure T(J+1); compare via the u1a paired
     comparator (A_BETTER / B_BETTER / FLAT — sign test against measured sigma).
  C2 other side: if J+1 not better, return to J, then step the other way; measure T(J-1).
     Both worse or flat -> return to J, ANCHOR (r8's landing was right).
  C3 climb loop: in the winning direction, step; settle; measure; BETTER -> continue;
     not better -> step back one; ANCHOR at the best measured rung.

ANCHORED: zero moves (owner thrash definition — climb moves are search, the anchor is
terminal). RE-ARM: r8's existing band-escape / demand machinery detects workload change and
starts a fresh J+C episode; during quiet the signal only watches, never moves.
An idle boundary anchors in place with zero moves; a non-idle workload shift remains bounded by
the per-state backstop and starts a fresh measurement era through the normal post-anchor r8 re-arm.

## First work and idle hysteresis

Boot and every sustained idle period arm one immediate search. Two consecutive loaded controller
samples (about 0.5 seconds at 4 Hz) establish the idle-to-serving transition. That transition primes
only r8's existing cadence gates and invokes its decision on that confirming sample, so its
direction, jump distance, stop conditions, and throughput judge are unchanged; if r8 requests no
jump, r10 begins C0-C2 at the held boot split immediately.
While r10 is active it remains the sole shape authority.

Idle is deliberately harder to establish: eight consecutive empty controller samples (about two
seconds, using r8's existing no-retired-work/no-queue/no-ingress `node_idle` observation) are required
to re-arm. A shorter traffic gap leaves the node in the same serving era and cannot start a second
search. A server that receives no loaded sample never transitions and never searches.
`tomokv_flip_first_work_searches` counts the per-node transitions that invoked this path.

## Laws honored
* No tables, no machine constants: improvement threshold = u1a paired-window sign test against
  the live A/A sigma; settle detected, never assumed; windows are the u1a sub-window cadence.
* Single authority: r8's actuation is GATED OFF from climb entry to re-arm — the climb engine
  owns the shape; no dual-controller fighting.
* Sweep-abandon LAW: every comparison is between HELD shapes in settled windows (timeline
  separation); the climb never polices itself with a signal it is concurrently moving.
* Thrash: a full episode is bounded (baseline + 2 side probes + climb rungs; single steps);
  suite verdict must be STABILIZED_CLEAN with post_stable_moves=0.
* Per-node: climbs run per node judged on that node's own ops (fc->mean is per node). If
  cross-node contamination shows in validation, serialize with a probe token (u1 design).

## Why this fixes the measured r8 failures
* get_p16 (landed io8, best io11, +13% first neighbor): C1 measures +13% >> sigma -> climbs
  through io9 (+13%) io10 (+10%) io11 (+8%) -> io12 flat/worse -> anchors io11. EXACT.
* mget8 (never armed): r8's demand gate still gates the JUMP, but the climb phase always runs
  at least C0-C2 from wherever r8 sits when load exists — the both-sides probe is
  unconditional per episode, so a dead jump cannot strand the shape at the boot split.
* set_p1 (overshoot io14 vs io13): C2 probes the back side and measures io13 better. EXACT.
* Flat optima: first not-better step anchors — lands within one rung of the peak, which is
  what the >=0.95 gate needs (the plateaus are 2-4%).

## Cost
Episode adds ~1-2 min of search after the jump (settle+window per rung, ~4-8 rungs typical).
Accepted by owner ("way longer"). Steady state cost: zero (anchored, quiet).

## Relation to m1
Modes: auto = r8+climb (this), model = m1. Both kept (owner). The climb's telemetry (delta
rungs from J per workload era) is also the live record of r8's proxy bias — logged for
analysis, never consumed as a table.
