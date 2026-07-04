---
name: thredis-zerocopy-keep
description: Zerocopy is a KEEP (value-size-gated), not a delete — wins +20-24% on 16-64KB values
metadata:
  type: project
---

DECISION REVERSED (2026-06-20): do NOT delete zerocopy in v8. The 6h sweep's "drop zerocopy" verdict was made at 64B payload (out of its regime). A focused isolation test (pure GET, 20k keys, ALLON vs NO_ZC) shows zerocopy's contribution by payload: 64B +0.3% (noise), 1K +2.9%, **16K +23.8%, 64K +20.9%**, 256K +6.5% (taper = memory-bandwidth wall ~13GB/s). Its whole purpose is avoiding the value memcpy on the reply path, so it pays exactly on large values (common: JSON/HTML/blobs 4-64KB).

PLAN: keep zerocopy + the S8 free-back ring; convert to a VALUE-SIZE GATE `zerocopy-min-value` (~1-2KB default): off below (free on small values), auto-on above (captures the win). The adaptive form — gated by the signal that predicts when it pays (value size), same pattern as prefetch (gate by miss-rate). Fits the unified `0=off` int-knob model.

LESSON (the v8 thesis): sweep "drop it" verdicts are only valid in the regime swept (64B, 1M keys). Opt GATING SIGNALS matter more than static on/off. See [[thredis-benchmarking-methodology]] — future sweeps must include a large-payload axis (16K-256K) with an isolated zerocopy arm.
