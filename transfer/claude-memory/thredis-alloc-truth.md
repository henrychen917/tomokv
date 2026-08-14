---
name: thredis-alloc-truth
description: 2026-07-27 — cross-thread alloc ownership MEASURED and disproven (~0.3% ceiling); the real lever is allocation COUNT; csGroup inline/SSO gives mget4 −5.2% instr/op; operand pool deleted as net-negative
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

## The cross-thread ownership theory is DISPROVEN — do not revisit without new evidence

Instrument built for it (`DEBUG TOMO-JESTATS`: per-thread jemalloc `thread.allocatedp`/
`deallocatedp` registered once at startup, zero steady-state cost, plus tcache `nfills`/`nflushes`
and small-bin `nrequests`). Bytes DO cross threads in the predicted direction:

| workload | cross-thread B/op | % of total alloc | flushes per KB |
|---|---|---|---|
| GET | 0 | 0% | 0.0777 |
| MGET(4) | 315 | 4.2% | 0.0950 |
| MSET(4) | 384 | 4.7% | 0.0989 |
| SET | 96 | **27%** | 0.1000 |

**But it costs nothing.** tcache flushes track TOTAL ALLOCATION VOLUME, not cross-thread share — a
27%-crossing workload (SET) and a 0%-crossing one (GET) sit within 29% on the very metric the theory
says should separate them by orders of magnitude. perf: all `tcache_bin_flush*` = **2.55% of server
cycles** under mget4, of which only ~11% is attributable to crossing.
**Ceiling on eliminating ALL cross-thread ownership on the M-path: ~0.3% of cycles.** Not worth a
mechanism. (My earlier attempt to support this theory from commit 52200d263's profile was also
wrong — see [[thredis-prefetch-truth]] and docs/BUGS.md §I2.)

## The real lever is allocation COUNT

GET 2.23 · SET 5.26 · **MGET(4) 26.00** · MSET(4) 38.43 allocations/op.

## What shipped (branch 2s-numa-alloc-dev, commit 968565c72)

`csGroup` carries a bump region inside its own allocation; coordinator-owned arrays are carved from
it and spill to `zmalloc` above capacity (`csgAlloc`/`csgFree` distinguish by address range). Three
invariants make it safe: **bump-only** (so the single memset is the only zeroing), **single-threaded**
(dispatch / HOP2-launch / pipeline-stages / reassemble all run on the group head's IO thread), and
**spill-always-legal** (an arithmetic slip degrades to old behaviour, never to a bug).

| workload | instr/op | allocs/op |
|---|---|---|
| mget4_p8 | **−5.21%** | 26.01 → 20.33 |
| mget4_p32 | **−3.86%** | 26.93 → 21.26 |
| mset4_p8 | −0.61% | 38.52 → 37.53 |
| get/set p32 (controls) | −0.09% / +0.00% | unchanged |

Self-checking: 5.69 measured inline allocs/op vs 5.73 predicted from command shape (3 fixed arrays
+ E[distinct shards] 2.73).

**A FIXED region size was wrong, and measuring caught it.** At a flat 320B, MSET (which uses exactly
one 32B inline array) paid 288B of pure memset + cache footprint: mset4_p32 came out **+1.27%**.
`csInlineWant` now derives the size from each command's own shape — which is also why there is no
knob for it.

## Knobs deleted, with the A/B a deletion requires

- **`tomokv-opt-operand-pool` — net-NEGATIVE everywhere**: instr/op +2.18…+4.13%, allocs/op
  **+6.6…+15.7%**. Structural, not a tuning miss: to be poolable an operand had to be RAW, so every
  miss cost robj+sds (2 allocations) where the normal path allocates ONE embstr. Its header's stated
  invariant was also false (the SET value operand is consumed on a worker, never reaching
  `freePendingCommand`).
- `tomokv-xshard-inline-bytes` (never shipped).
- KEPT: `tomokv-modeshift-test` (write-only actuator, not inert), coalesce/localfast/pipeline
  switches (live behaviour levers), `pcmdPool` (recycles struct+argv ARRAY, not elements — a
  different trade).

## Quantified but deliberately NOT taken

`sub->argv` is 4 more allocations per MGET(4)/MSET(4). It is owned by the CLIENT, not the group:
`replaceClientCommandVector`'s isFake branch calls `zfree(c->argv)`, so any sub running a real proc
could free an interior pointer of the group region. Making it safe needs a whole-codebase claim
about which procs can run on a sub — above the bug-risk threshold this design deliberately stays
under.

## HARNESS HAZARD (bit two agents; now permanent rule 2b)

**`pgrep -x` cannot tell you the box is idle.** Agents rename their binaries (`tomokv-bench`, `mtb`)
so a foreign `pkill -x` cannot reap them — which also hides them from an exact-name idle check.
Measured live: `pgrep -x redis-server`=0, `pgrep -x memtier_benchma`=0, **CPU 98% busy**, two renamed
processes running. A confirmation bench measured 608k instead of 1.6M ops before the sanity gate
caught it. Use a CPU-load-first check (`$J/boxfree.sh`). Same root cause as the `comm` 15-char
truncation trap in [[thredis-ab-harness-traps]].
Also: `correctness_suite`'s `ordering-under-load` drives its own churn and is timing-sensitive — a
lone failure under contention is suspect until reproduced on an exclusive box.
