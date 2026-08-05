# D phase 2 — designed, grounded in the code, deferred to the multi-CCD box

Steps 1–5 + D5 aging are done, pushed, and gated (`d_reorder.sh`). The three remaining phase-2
mechanisms below are **spec'd against the actual code** but **not built**, on a deliberate call:
each is either DRAM-bound-only or multi-node-only, so its benefit is unmeasurable on this
single-CCD, single-node, cache-resident-by-default box. Building an unverifiable mechanism blind is
the exact failure this week's work kept catching (vacuous-validation, wrong-two-quantities). They
are built and A/B'd on the Threadripper/EPYC box, where the regime that motivates them exists.

## 1. EX cache-readiness scoreboard (the phase-2 core)

**Where it hooks.** `exSlice`, after `exPrefetchBatch(ctx->batch, n)` (server.c ~17185) and inside
the `for (j = 0; j < n; )` exec loop (~17206). The prefetch is already issued batch-ahead; readiness
is the *completion* half of that same machinery.

**Scoreboard, no new struct.** For batch entry `j`, "issued distance" = its index; "elapsed" =
commands executed since the batch head. Entry `j` is READY when `executed - issue_index[j] >= k`.
Both are integers the exec loop already tracks — no clock, no probe (touching the line to test
residency *is* the miss — the invariant this whole design respects).

**k and K are learned, not set.** Reuse the step-1 svc plane, bucketed by distance-from-issue:
sample exec time at each distance, `k` = smallest distance whose sampled time sits at the class
floor (prefetch has landed), `K` (abandon horizon) = the distance past which times rise again
(evicted). One extra dimension on the existing `svc_us/svc_ops` rows. The same samples are the
efficacy check — mean exec at distance ≥ k vs < k — so engagement and benefit are one measurement.

**Reorder, bounded by the SAME aging.** Within the popped batch, defer a not-yet-ready entry
(execute a later ready one first), capped by `TOMO_RORD_AGE_BOUND` displacement — the identical
chunk bound already shipped, so the starvation story is unchanged. `worst_age_us` already covers it.

**Why deferred.** The prefetch gate is measured 100 % SHUT in the cache-resident regime
(2M×32B; docs/ABCD_D_DESIGN.md B-table) — zero prefetches issued means zero readiness signal, so
the mechanism is inert exactly where this box runs by default. It engages only DRAM-bound
(8M×32B / large values), and the stall it hides is largest cross-CCD. **Verify: build behind a
sub-level, prove the scoreboard fires + defers in an 8M-key regime, prove cost-neutral where the
gate is shut, then read the tail benefit on EPYC.** CAUTION: this is surgery on the hottest,
most-sentinel-laden loop (drain-ack, flush, cross-shard sub barriers all live in that `for j`) —
the reorder must skip every sentinel/sub exactly as the IO-side front does.

## 2. Inverse-heat prefetch targeting

**Where.** The prefetch issue site (`exPrefetchBatch` / the `#3` next-op prefetch, ~17206), which
already has each command's bucket.

**Rule.** Spend LFB slots on COLD-bucket keys (a prefetch there buys a full miss) and skip
HOT-bucket keys (likely already resident) — heat from the existing `lb_grp_ops` group counters,
read-mostly, no new signal. Improves the prefetch the §1 scoreboard then tracks.

**Why deferred.** Same gate: only matters DRAM-bound, and hot-vs-cold only separates when the
working set exceeds L3. Measure on the large-DB / EPYC regime.

## 3. Multi-node data-home topology term (reorder level 3)

**Where.** The run-emit outer loop in `tomoReorderDrain` (server.c ~2765). Runs are already grouped
by worker index, which is per-node contiguous on this arch (`tmNodeOfWorker`), so they are ALREADY
node-grouped as a side effect. Level 3 adds only "this IO thread's OWN node's runs first"
(`tmNodeOfIoSlot(iotid)`), batching cross-node argv/operand transfers instead of interleaving them.

**Why deferred / not built.** Total no-op on a single node (all runs same node), and there is no
second node here to exercise `tmNodeOfIoSlot`'s divergence. The spec also names a THIRD location on
`numa≥2` — the data's home node, which can differ from both the io and ex node — same signal family,
only meaningful with real cross-node placement. Build with the numa≥2 path, on the multi-node box.

## The through-line

Every phase-2 mechanism's payoff lives in a regime this box cannot produce (DRAM-bound stalls,
cross-CCD interconnect, multi-node placement). The single-CCD verdict on the whole reorder is
already in `docs/D_RESULTS_2026-08-06.md`: correct, cheap (−2–3 % throughput), a tail trade that
D5 aging makes safe. Phase 2 is where the *upside* is, and it is measurable only on the target
hardware — which is exactly why it is deferred rather than declared.
