---
name: thredis-worker-overhead-bound
description: "CORRECTED 2026-08-11: the '2.0M/worker ceiling' was an ARTIFACT — workers are ~27% busy at io4ex4 p32 saturation; the IO SIDE is the binding constraint (instruction-bound, 2.9x below its own pure ceiling); true worker busy-cost ~140ns/op vs rig 95ns"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

# CORRECTION 2026-08-11 — the ceiling was never the worker's

The zero-cost saturation check the Opus census demanded (tomokv_ex_busy_us vs wall) finally ran:
io4ex4 p32 GET 100K @ 7.84M ops/s => ex_busy 32.9s over 120 thread-seconds = **workers 27% BUSY**.
Wall-clock worker "IPC 1.17/0.78" was SPIN-DILUTED garbage. True worker execution cost =
32.9s / 235M ops = **~140ns/op busy** (rig 95ns => real handoff tax on the worker ~45ns, not
400ns). The famous "2.0M per worker in every config" held because those configs scaled BOTH
sides together — per-worker rate mirrored the per-IO feed rate. Counter-evidence that was
always there: io7ex1 p32 GET pushes 4.4M/s through ONE worker.

**The binding constraint at io4ex4 p32 is the IO SIDE**: 1.96M cmds/s/IO-thread, IPC 1.65,
low stalls, flat profile (= instruction volume), vs its own pure-rig ceiling 5.69M/s/thread.
This explains, in one stroke: the controller's certified io5ex3 SET optimum (it shifts a core
to the true bottleneck), all three neutral line-warming results (they optimized the starved
side — [[thredis-commtax-truth]]), and the dataset-scaling flatness below (an underfed worker
hides its own miss latency in idle time).

CONSEQUENCE: perf effort goes to IO-side per-command instruction diet (dispatch entry ring,
pendingCommand/reset diet, clock diet, drain diet, syscall reduction/uring) and to
ASYMMETRIC thread configs. The worker-side 500ns census below is OBSOLETE as a priority.
Fresh caveat from the same check: worker busy-IPC and the worker's remaining stall split are
still unmeasured (needs spin-excluded sampling); only ~140ns of budget lives there.

# Original 2026-08-02 entry (kept for the record — its conclusion is now known wrong)

## The two measurements

**Dataset scaling** (io4/ex4 p32, random GET, prefetch off):

    2M keys   243 MB   7,896,532 ops/s
    8M keys   785 MB   7,897,455
    24M keys  2.35 GB  7,772,769
    48M keys  5.14 GB  7,618,184

**3.5% loss for a 21x dataset increase** — from 7.6x L3 to 160x L3. A memory-bound workload
collapses here. This does not.

**Thread-config sweep** (24M keys, prefetch off):

    io4/ex4  7,797,864   ->  1.95M per worker
    io5/ex3  6,263,660   ->  2.09M per worker
    io6/ex2  4,074,672   ->  2.04M per worker

**Per-worker throughput is ~2.0M ops/s in EVERY config.** So the workers are the ceiling —
including at io4/ex4, which I had wrongly called "dispatch-bound". Starving them lowers absolute
throughput ~20% exactly as intended but does not change what the ceiling is made of.

## The conclusion

Per-worker throughput is pinned regardless of config, while a 21x dataset increase costs 3.5% ⇒
**the worker is limited by fixed per-command WORK — fake-client setup, dispatch bookkeeping, reply
construction, the command proc — and NOT by cache misses.**

## What follows

* **Prefetch cannot pay here.** It hides memory latency, which is not the constraint. Confirmed a
  wash at every size and every config with 173–356 M prefetches genuinely issued
  ([[thredis-prefetch-truth]]).
* **The lever is reducing per-command work**, not hiding latency.
* **But do the census FIRST.** The worker spends ~**500 ns per command** (1 / 2.0M) and nobody has
  decomposed it. Allocation is only one term. `perf record` a worker at io5/ex3 p32 and attribute
  that 500 ns across: allocation, fake-client setup, dispatch bookkeeping, reply construction,
  command proc. Two allocation guesses already cost −18.4% (per-command arena) and a deleted
  subsystem (operand pool) — see [[thredis-alloc-truth]]. A third guess is not warranted when the
  census is a day's work and says whether allocation is 5% or 40% of the budget.
* **`io5/ex3 p32` is the standing EX-side cell** (owner ruling 2026-08-02): ~20% lower throughput
  concentrates load on fewer workers, so a real EX regression shows proportionally larger than at
  io4/ex4. It does **not** manufacture a memory bottleneck the workload lacks.
* Re-measure all of this on the multi-CCD 24-core and 96-core parts — a miss costs far more there,
  so the balance between "per-command work" and "memory stalls" may genuinely differ.

Related: [[thredis-prefetch-truth]], [[thredis-alloc-truth]], [[thredis-final-server-specs]],
[[thredis-benchmarking-methodology]].
