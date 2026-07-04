---
name: thredis-forwarding-deadend
description: "Value-forwarding (#4/#7) is a throughput dead-end — proven across every regime; keep it only as a gated do-no-harm opt + a paper negative result"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

Value-forwarding (read-run same-key value reuse, opt #4/#7) does **not** convert to throughput on THredis, proven exhaustively (2026-06-21). Stop trying to make it a win. **DISABLED by default (2026-06-21):** `thredis-opt-value-forward` default flipped to 0, so `m` stays 1 in the worker loop and all forwarding machinery (run-scan, record/replay, cost gate, early-signal, predictor) is bypassed. Code kept in-tree as the paper negative result; flip to 1 to re-enable. (Contrast [[thredis-prefetch-status]] — prefetch is NOT a dead-end and stays ON.)

**The decisive test:** single hot key ⇒ every op is a forwarded replay (MAXIMAL forwarding, no scan waste) + zerocopy (replays skip dictFind AND re-serialization). Flat at every value size: 64B 1.9M→1.9M, 1KB 1.21M→1.21M, 16KB ~220K→~229K, 64KB ~48K→~47K. Even maximally triggered with serialize removed → ~0 gain.

**Why (mechanistic — the real answer):** forwarding removes a hot-key dictFind (cache-warm ≈ free) + one serialize copy. The per-op bottleneck is elsewhere: network RTT, syscalls, ring dispatch, and for big values the socket-write memcpy zerocopy can't remove (bytes must reach the kernel). **It removes a non-bottleneck.** For complex types it doesn't even remove the serialize (zerocopy is string-only) → removes only the free dictFind. And on real workloads runs barely exist (mean run length 1.008 — Meta trace) so it fires <1% of ops. Triple bind: saves the wrong thing, rarely fires, taxes every read with the run-scan.

**Also dead (all neutral-or-worse):** cost-benefit gate `thredis-vf-min-saved` (§16), early-CDB `thredis-vf-early-signal` (un-coalescing the reply signal per-run is worse — worker is the bottleneck, not IO drain), predictor tuning, thresholds, big DB/payload, LRANGE complex. See [[thredis-zerocopy-keep]] (zerocopy itself wins on big *values* — that's separate from forwarding).

**Keep it anyway as:** (1) a correct, gated, do-no-harm opt (cost-benefit gate makes on-by-default safe); (2) a reported **negative result** in the paper — completes the Tomasulo value-forwarding analogy and shows where the CPU-microarch analogy breaks for KV (I/O-bound not compute-bound; key streams lack runs).

**CDB signal:** coalesced/batch CDB beat per-op "serialize" by +0.4–0.7% in the sweep (grows on multi-CCD). Keep batch CDB.

**Only unbuilt lever that could help compute-bound reads:** serialized-reply *memoization* (cache op_0's reply BYTES, replays memcpy/share them) — distinct from value-robj forwarding. Ceiling = serialize cost only (socket write still happens), still needs runs → expected marginal. Real micro-arch win is prefetch, not forwarding: see [[thredis-opt-and-testers]].
