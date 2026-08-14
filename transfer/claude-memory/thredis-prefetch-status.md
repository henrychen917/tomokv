---
name: thredis-prefetch-status
description: "Prefetch is KEPT ENABLED (not a dead-end) — but its \"+16% cold-dict\" was thermal-drift on this laptop and is unconfirmed; re-measure on EPYC"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

THredis worker+IO prefetch stays **ENABLED by default** (`thredis-opt-prefetch-worker/-io/-hash-carry` = 1). User judged it **NOT a dead-end (2026-06-21)** — prefetch targets real cold-memory latency that this hybrid laptop barely exposes (small dies, E-core throttle, single memory domain), so it's exactly the kind of opt expected to pay on the EPYC/multi-CCD target.

**Caution (don't cite as established):** the reported "+16% cold-dict prefetch" (report §14) did NOT reproduce under interleaved + order-alternated measurement in its own regime (10M×1KB, 1:9): ON vs OFF sign-flips run-to-run within ±4% — a wash on THIS box, and it even *hurt* in the dispatch-bound 4M×64B regime. Root cause was recorded as ~15% thermal run-to-run drift — but that figure is the LAPTOP's; the 7700X dev box is **±2% exclusive** ([[thredis-box-noise-truth]]), so on this box a swing that large means CONTENTION or a bug, not drift. The interleaving conclusion still stands; the stated cause may not (see [[thredis-benchmarking-methodology]] — interleave is mandatory for <10% effects). So: keep prefetch on, but **re-measure on real EPYC HW with interleaved methodology before making any +X% claim.**

Value-size-adaptive pf-w-value (`thredis-pf-w-value-adaptive`) was built but is a no-op here (all widths within ±2-3% once drift controlled); left as a gated-off knob.

Contrast with [[thredis-forwarding-deadend]] — forwarding IS a dead-end and is now disabled by default; prefetch is not. Real drift-proof wins: jemalloc (+30-54%, [[thredis-jemalloc-and-overnight-findings]]), LB (+133%), architecture.
