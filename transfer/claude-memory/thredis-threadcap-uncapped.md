---
name: thredis-threadcap-uncapped
description: "#66/#83 DONE — IO/EX thread caps raised 32/64 -> 128/128 (commit 2a7c831a3 on 2s-numa-stable-dev-work, NOT pushed). All >64 walls cleared: heap-sized lanes+heap-FAST, ex_dirty_mask/io_pin_mask word arrays, snap[] premature-free clamp, q_summary single-word gate. + two build/harness gotchas."
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-05. Removed the 32-IO / 64-EX compile ceilings. `TOMO_IO_THREADS_MAX` and
`TOMO_EX_THREADS_MAX` are now **128/128** (server.h). Commit **2a7c831a3** on
`2s-numa-stable-dev-work`. **NOT pushed** — needs owner go + a full preflight GO stamp
([[thredis-preflight-contract]]).

**Why:** unlocks the multi-CCD / many-core payoff on the [[thredis-final-server-specs]] Threadripper
(24c/48t) and future EPYC. Design goal (owner): "uncap path only when we actually set thread values
that needs it" — a normal small-thread boot must pay nothing for the raised cap.

## Walls cleared (each was a real >64 correctness/perf trap)
1. **lanes** — exThread `queues[]`/`freeback[]` were inline arrays sized to the compile cap
   (~802KB/worker). Now ONE heap block per worker sized to the runtime pool (io+workers+1), so cap
   128 costs the same as cap 32 at a given thread count. heap-FAST recovers the pointer-load: hoist
   `WQ=worker->queues` out of the exSlice pop loop + TLS-cache the dispatch base in `exQueueFor`
   (`tls_qbase[]`). Measured **heap == inline** (+-0.4% instr/op io4ex4).
2. **ex_dirty_mask** uint64 -> `uint64[TOMO_EX_MASK_WORDS]`; consume loop bounded by live words.
3. **QSBR io_pin_mask** uint64 -> `uint64[TOMO_IO_MASK_WORDS]`, and io_snap/snap sized via
   flatstore.h mirrors `FLAT_IO_SLOTS`/`FLAT_EX_SLOTS` (flatstore.h can't see server.h; bound by
   `_Static_assert` in server.c). **io_pin_mask is FULL-cleared on close** — flatBatch headers are
   pool-recycled, a stale high-word bit => premature-free (UAF) or never-ready (leak).
4. **flatBatchClose** had a HARD `nw > 64 -> 64` clamp on the loop_seq snapshot (snap[] was [64+1]);
   at cap 128 that dropped workers 64..127 from the grace check => premature free. Now clamped to
   `TOMO_EX_THREADS_MAX`.
5. **SCAN cursor** `TOMO_SCAN_WORKER_BITS=8` already encodes worker 0..255 — 128 fits, no change
   (wall is past 256).
6. **q_summary single-word gate** — raising the cap makes `TOMO_QS_WORDS` 1->3, which activated the
   two-level (q_top atomic per exSlice pass) harvest even at 4 threads (+0.95% GET instr/op). Since
   `io_hi <= io_threads + num_workers`, latch `server.tm_qs_multiword` at boot (`initExThreads`);
   when that sum < 64 the process never touches word 1 and advertise/harvest take the exact
   single-word path. Recovers GET to +0.4% (residual = cap-128 struct size, within the 3% budget).
   Process-constant => no transition hazard. This is the mechanism that makes the raise perf-neutral
   at normal configs — grep `tm_qs_multiword` before touching the handoff.

## Validation (cap 32 AND cap 128, both modes of the gate)
d_reorder 4/4 (single-word + gated) · heap-FAST A/B heap==inline all 8 cells · ASAN cap-32 churn
no-UAF through 12+11 flips · release stress_reclaim ALL-PASS no leak (16+16 flips) · cap-128 boots
io68ex68 + serves + multi-word dispatch correct (hi83 5/5, pre-gate and gated) · ASAN cap-128
multi-word churn no-UAF dbsize intact · cap-raise A/B +0.4% instr/op ops-flat. Harnesses:
`$J/hi83.sh` (>64 boot+correctness), `$J/asan128hi.sh` (multi-word ASAN churn), `$J/capab.sh`
(cap32-vs-cap128 A/B).

## Still open / out of scope
`argv_released_mask` (server.c:17252) is a `uint64` over **argv indices** — a SEPARATE >64-wall for
commands with >64 keys (huge MSET/MGET), guarded by `if (a < 64)`. Pre-existing, NOT thread-related,
still open. Per-slot stat arrays (kstat/cmdstat/netstat/errstat, `TOMO_STAT_SLOTS` 97->257) grow
~100KB in the single redisServer instance — noise, accepted.

## Two gotchas hit this session
- **Sticky `.make-settings`**: `make SANITIZER=address` leaves jemalloc DISABLED; a subsequent plain
  `make USE_URING=yes` comes out `malloc=libc` AND may retain `__asan_` symbols — you can nearly
  A/B on a contaminated binary. `make distclean` before a clean jemalloc release build; ALWAYS
  verify `--version` malloc= field + `nm | grep -c __asan_` before trusting a build's identity.
- **BGSAVE fork child** shows in `ps` as `redis-server` with `ppid=<server>` and `rss≈0` (COW). Don't
  false-alarm the one-server rule on it — filter by ppid / rss>0. (Also: ASAN inflates RSS ~3x via
  shadow+quarantine, so stress_reclaim's BASE+1500MB RSS gate FAILS spuriously under ASAN — judge
  UAF/crash from ASAN, judge leak/RSS from the release build.)

Related: [[thredis-flat-reclaim-capacity]] (the reclaim path this stresses), [[thredis-flatstore]],
[[thredis-final-server-specs]] (where the payoff lands), [[thredis-sanity-gate-benching]].
