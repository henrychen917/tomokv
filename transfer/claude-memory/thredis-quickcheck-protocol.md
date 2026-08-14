---
name: thredis-quickcheck-protocol
description: "USER RULE — the standing 8-cell quick check for any hot-path change: p32/p1 x GET/SET at io4ex4 and io7ex1, static mode; no flip check needed unless LB code changed"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Owner ruling 2026-07-28:

> "always do four quick things to check, p32 get p32 set, p1 get p1 set. 4 4, 7 1 no need to check
> flip if we don't touch lb stuff"

## The protocol

Eight cells, run before anything else on a change that could touch the hot path:

| workload | thread config |
|---|---|
| p32 GET, p32 SET, p1 GET, p1 SET | **io4/ex4** and **io7/ex1** |

Both with `--tomokv-thread-mode static`. ABBA-interleaved, medians.
Script: `$J/quickcheck.sh <armA-dir> <armB-dir> [reps]` (arms differ by DIRECTORY, binary named
`redis-server`, so the suites' `pkill -x` cleanup can reap them).

## Why these eight, and why no flip check

- **p32 vs p1 are opposite bottleneck regimes.** p32 is pipelined/throughput-bound (dispatch and
  batching dominate); p1 is per-round-trip/latency-bound (wake-up and syscall path dominate). A
  change can be free in one and costly in the other.
- **io4ex4 and io7ex1 are the two ENDS of the flip curve** — io4ex4 is the p32 optimum, io7ex1 the
  p1 optimum (matches the measured static p1 curve 595/714/814/833k and the controller settling at
  io7/ex1 for p1, io4/ex4 for p32; see [[thredis-flip-controller-momentum]]).
- Running both **static** configs covers both regimes *without* waiting for the flip controller to
  converge — which is why **no flip/LB check is needed unless LB code changed**. Convergence
  transients are ~11% ([[thredis-flip-overhead-decomposed]]) and would swamp a small delta.

## Metric

**ops/s.** NOT instr/op: the EX workers busy-spin (`exPauseCpu`), so a process-wide instruction
count partly tracks idle time rather than work — measured ~15,000 instr/op for a plain GET, 3-5x
the real cost. instr/op remains correct for allocation-COUNT work. See
[[thredis-ab-harness-traps]].

Compose with [[thredis-three-regime-testing]] for ambiguous features, and hold the box lock for the
whole run ([[thredis-box-noise-truth]]).
