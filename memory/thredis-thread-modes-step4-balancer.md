# THredis thread-modes STEP 4 — quorum pressure balancer (2s fork, 2026-07-05)

Working tree: /shared/Projects/THredis-v13-2s-autothreads (UNCOMMITTED at time of writing).
Knobs: tomokv-thread-balance (bool, MODIFIABLE, requires thread-modes at boot else FATAL-warn+ignore;
runtime enable rejected without thread-modes); tomokv-ex-threads-min/max + io-threads-min/max
(0=auto; v1 bounds only the spare; io bounds INERT in v1).

## What works (validated 2-cycle smoke, port 7913, io3/ex2 + spare)
- Autonomous PARKED->EX 2.6-2.8s from HGETALL-storm onset (quorum 5/6, settle 12 ticks @ ~200ms);
  autonomous EX->PARKED 1.4-3.8s into io-heavy 64B phase (capacity-projection vote), MID-traffic.
- Conservation exact at every phase boundary; p99 veto fired once, froze 12 ticks, one-shot doubled
  settle (24) then restored — full guardrail loop exercised.
- Hardening: FLUSHALL during deactivation → dbsize 0 (no resurrection); pending-park AND
  pending-migration modeshift requests reject loudly (silent-OK killed); coordinator clears
  tm_mig_spare_action BEFORE migration_active=0 release.

## Calibration lessons (each was MEASURED broken then fixed — don't regress)
1. busy-by-PASS-counts reads ~0% on a saturated worker (50ns spins vs 100µs work passes).
2. busy-by-IDLE-EPISODES (yields) reads 100% on a 10%-duty worker (adaptive spin window absorbs
   burst gaps — never yields). BOTH ratios unusable for votes.
3. busy vote uses TIME: tm_busy_us = first-pop..fold per work pass (2 vDSO reads/work pass, none
   per spin poll). Grow: smoothed max >= 75. Shrink: capacity projection mean*n/(n-1) <= 75*7/8.
4. Queue-depth bands must be CONCURRENCY-normalized (vs rob in-flight), not capacity-normalized:
   closed-loop load gens bound standing depth by their window (cap/8 unreachable). Plus absolute
   OR-band (8 pop-batches behind) for the drain-lag regime.
5. cached_tail leftover under-reads standing depth ~2x (refreshes only at cache-empty) — sampler
   uses real tail acquire, work passes only.
6. Sustain is SCHMITT: quorum ticks count up, borderline ticks HOLD, clear-miss resets (200ms
   sampling beats against burst cadence; plain consecutive-AND never fires).
7. p99 veto: watch gated on !migration_active + skip 2 ticks (ring turnover) — else it vetoes the
   migration's own transient (25-30ms holds).

## PRE-EXISTING BUG found (NOT step-4, NOT thread-modes): mass-hard-kill livelock
Hard-killing a deep-pipeline benchmark (48c x P16 HGETALL 5KB) leaves ~223 fakes never retired →
every freeClient defers + requeues in freeClientsInAsyncFreeQueue forever; main + io threads spin
~100% in free/requeue/listAddNodeTail (perf-verified), some conns unserved. Reproduces with
thread-modes OFF (legacy v13-2s). Graceful benchmark completion (finite -n) avoids it. Root cause
untraced: which fakes never complete + why CLOSE_ASAP drain misses them. Repro:
`redis-benchmark --threads 6 -c 48 -P 16 HGETALL 'h:__rand_int__'` + timeout-kill mid-flight.

## Signals (all owner-written plain fields, racy control-plane reads)
exThread: tm_qdepth_ewma_q4 (standing backlog EWMA a=1/8, work-pass folds + yield 0-folds),
tm_work_slices, tm_idle_episodes (exported per spec; not vote drivers), tm_busy_us.
tm_io_sig[iotid] (padded, server.c): busy_ewma_q4 (events/pass via ioSlice; main thread NOT
covered — runs aeMain), rob (replyWorking published in beforeSleepIO/beforeSleep), lat_ring[64]
(1/1024 dispatch stamps on fakes, retired at drain; client.tm_lat_stamp).
Balancer: tomoThreadBalanceCron in serverCron run_with_period(250); actuator tomoSpareShift
(factored from tomoModeshiftSpare, both = manual override + balancer, main thread only).
