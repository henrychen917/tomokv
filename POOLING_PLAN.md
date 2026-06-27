# Operand pool v2 — size-class tiers + demand-grow + independent decay (MULTI-STAGE)

## Why (user, 2026-06-27)
"i didn't say 3 stage, i said multi stage … some workloads might have a wide range of requests."
A single flat LIFO operand pool reuses a wrong-sized buffer (realloc on grow, memory bloat on shrink),
and in the 3-stage split it frees CROSS-THREAD (parse on ifid, retire on wb = the ~17% instr/op balloon,
jemalloc tcache flush). Make the pool **size-class tiered** so reuse matches buffer capacity, the pool
self-sizes to in-flight concurrency, and idle classes decay back. This is a **multi-stage** improvement —
benefits 2-stage AND 3-stage. The cross-thread recycle ring is the 3-stage-only add-on.

## Structure (per OWNING thread → single-threaded access → no locks)
`tier[NTIER]` size classes by sds capacity, e.g. {≤64, ≤256, ≤1K, ≤4K, ≤16K, >16K = direct malloc, no pool}.
Each tier = { free: LIFO of `robj*` with `sdsalloc ≥ class`, inUse, hwmEwma (decaying demand high-water), idleTicks }.

## GET(len)  [parse]
t = tierForLen(len); if `tier[t].free` nonempty → pop, reset sds to hold len (fits, NO realloc), return.
else → malloc a fresh robj+sds sized to the class. **DEMAND-GROW: malloc only when every pooled entry of
this class is in-flight** (free list empty). inUse++.

## PUT(o)  [retire / re-file]
t = tierForCap(sdsalloc(o)); push o to `tier[t].free`; inUse--.   (file by ACTUAL capacity, not last value)

## Cross-thread return — 3-stage ONLY (preserves locality = the whole point)
wb retire does NOT free / does NOT PUT to wb's own tiers. It pushes o to `recycleRing[owner_ifid]` (SPSC,
wb producer / ifid consumer; stamp owner ifid at dispatch). The ifid drains the ring each beforeSleepIfid
and PUT()s into ITS tiers. Bounded ring; on full → decrRefCount (rare). **2-stage: parse+retire same thread
→ PUT directly, no ring.**

## Independent decay (per tier, on a periodic owner tick)
hwmEwma = ewma(hwmEwma, inUse); if `free > slack·hwmEwma` → free the excess; tier idle for K ticks → drain
fully. ⇒ traffic shifts 16K→64B: the 16K tier decays + releases memory while the 64B tier grows. Classes
decay independently.

## Gates
instr/op ~3900 → ~1650 (3-stage, perf stat cpu_core/instructions); correctness single + cross-shard; ASAN
clean; RSS stable AND decays after a class goes idle (soak the decay path); 2-stage neutral-or-better on
mixed sizes (no realloc churn). Knob-gate the whole thing (default behaviour preserved when off).

## Build/test note
3-stage REQUIRES `make USE_URING=yes` (else strict/threestage silently hangs — see memory). Server c0-7,
loadgen c8-15, jemalloc via LD_PRELOAD.

## Then (#84): 2-hour sweep — 2-stage vs 3-stage @ same total thread count × alloc (jemalloc/mimalloc/libc)
× epoll/uring; simulate varied-request-size workload, then memtier 1:9 + 1:1. (Confirm "simulate x" with user.)
