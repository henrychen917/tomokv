# Readability phase 1 comment corrections

## readability-p1fix

Base: `7595a6705ac19c1a4eecf7798fde594332f0be0c` (`origin/cpp`). Branch:
`cx-readability-p1fix`. Comments only in the A3–A6 ownership partition; generated
R7 envelopes are written only by `tests/r7shadow_sync.py --write` (also called by
`make format`). No push, full gate or benchmark is requested for this lane.

The final report will account for all 114 audit findings, record the frozen-metadata
binary comparison, raw preprocessing-token/literal/anchor equality against the base,
and the authorized selected gate jobs. No gate rows or expected counts change.

A3 source corrections restore the reclaim-tick provider, pub/sub ordering and
ownership, parser encoding, controller transitions, TLS preconditions, migration
lifetime, and the Phase 5 serving pointer. The matching `src/net/rob.h` pointer
belongs to A10 and is intentionally left for that lane. Four additional A3 audit
notes are corrected: the broken epoll sentence, repeatable arming after allocation
failure, the live-stage negative control, and the deleted-mode flush header.

Verification is in progress; final proof and the per-finding table follow in the
completion commit.
