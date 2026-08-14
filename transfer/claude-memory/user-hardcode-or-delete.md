---
name: user-hardcode-or-delete
description: "USER RULE — hard-code decisions; a change is a consistent gain or it's deleted; no knob to preserve a net-negative unless asked"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

When a change doesn't clearly earn its keep, the answer is NOT an opt-in knob (default off) that
preserves it. Two choices only: **lower its overhead until it is a consistent gain (hard-coded, always
on), or delete it.** Do not add a runtime toggle to dodge that decision.

**Why:** a knob-gated "neutral" change is dead weight — untested-on paths, config surface, and the
illusion that a net-negative is acceptable because it's off by default. The owner wants the shipping
build to be made of things that are each a real win, not a pile of switchable maybes. (This extends
[[thredis-knob-philosophy]]: knobs exist, but as deliberate, owner-requested tuning surface — not as a
hiding place for changes that would otherwise be cut.)

**How to apply:**
- Default to HARD-CODING a change's decision. Only add a knob when the owner explicitly asks for one
  (e.g. they asked for io_uring as a "third start option" -- that knob is wanted).
- If a change regresses the common path and can't be reworked into a consistent gain, DELETE it (full
  revert), don't knob-gate it. This is what happened to hashbytes byte-bounding
  ([[thredis-hashbytes-oN-regression]]): my opt-in/default-off commit was the wrong call; the owner
  said delete, and it was reverted.
- Pairs with [[thredis-forwarding-abandoned]] / [[thredis-unified-path-closed]] (neutral mechanisms get
  cut, not preserved) and the [[thredis-lb-3pct-budget]] / no-regression bar.
