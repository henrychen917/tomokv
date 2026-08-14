---
name: thredis-three-regime-testing
description: "USER RULE — when A/B-ing an ambiguous feature, test three regimes (predicted-benefit, predicted-neutral, predicted-deficit) and decide from the pattern, not from one number"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Owner ruling 2026-07-28:

> "when ur testing ambiguous stuff, test situation that would benefit it and one where neutral one
> where theoretically deficit then decide"

## The rule

Before measuring an ambiguous feature, write down the MECHANISM's prediction, then pick three
workloads:

1. **Predicted benefit** — the regime where the mechanism's theory says it must win.
2. **Predicted neutral** — where the theory says it should not matter.
3. **Predicted deficit** — where the theory says its overhead should exceed its saving.

Then decide from the PATTERN, not from any single cell.

**Why:** a single-regime A/B tests "is this faster here", which is a fact about the workload. Three
regimes test whether the causal STORY is true. A feature that wins in all three is not a triumph —
it means the stated mechanism is not what is producing the win, so the result will not transfer to
the real workload or the real hardware. A feature that loses in its own predicted-benefit regime is
dead regardless of what the other two say.

**Why it matters more on this box:** exclusive noise is ~+-2% ([[thredis-box-noise-truth]]), so a
lone 1-3% cell is barely above the floor and the temptation is to accept whichever sign is
convenient. A consistent three-regime pattern is evidence that survives that ambiguity; three
independent coin flips do not.

## Companion rules this composes with

- Pick the metric from the mechanism, not by habit: allocation/instruction work -> `instr/op`;
  PREFETCH work -> cycles/op or stall counters, because prefetch ADDS instructions to REMOVE stalls
  and instr/op reports the wrong sign ([[thredis-prefetch-truth]]).
- Prove the path actually RAN in each regime (ship a counter). A regime where the gate never opened
  is not a neutral result, it is a missing measurement ([[thredis-vacuous-validation-trap]]).
- **Check the feature is reachable AT ALL before designing regimes.** On the flat store every
  table-touching prefetch stage self-disables, so `pf-w-hash/entry/value/nextop` and
  `pf-value-budget-kb` cannot fire; a three-regime test of those would have produced three honest
  washes and the false conclusion "no gain" for entirely the wrong reason.
- Interleave arms and take medians ([[thredis-ab-harness-traps]]); hold the box lock for the whole
  run ([[thredis-box-noise-truth]]).
