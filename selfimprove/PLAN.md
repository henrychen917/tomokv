# Self-Improvement Loop — autonomous run to 2026-07-06 20:30 TW (12:30 UTC, epoch 1783341000)

User (2026-07-05 ~18:43 TW): run a self-improvement loop on ALL 4 forks until deadline (>24h).
Do it on NEW improve-dev branches (don't touch canonical stable/3-stage/auto-dev). Starts AFTER
the in-flight v1.6 connection-migration workflow completes (box is a serial bench resource).

## The 4 versions and their improve branches
| version | canonical branch / worktree | improve branch (NEW) | improve worktree |
| :-- | :-- | :-- | :-- |
| 2s static | stable / THredis-v13-2s | 2s-improve-dev | THredis-2s-improve |
| 3s static | 3-stage / THredis-v13-3s | 3s-improve-dev | THredis-3s-improve |
| 2s auto | 2s-auto-threads-dev / THredis-v13-2s-autothreads | 2s-auto-improve-dev | THredis-2s-auto-improve |
| 3s auto | 3s-auto-threads-dev / THredis-v13-3s-autothreads | 3s-auto-improve-dev | THredis-3s-auto-improve |
(Auto improve branches created AFTER v1.6 is committed, so they include it.)

## Per-pass protocol (one pass = one Workflow)
1. PARALLEL READERS (box-free, safe to fan out): 2-3 agents close-read assigned region(s) of the
   target fork. Each returns RANKED candidate edits: overhead-shave (remove redundant work, hoist
   invariants, kill non-pipelined idiv/syscalls on hot path), simplification, lower-level/lib swap,
   cache-friendliness. Each candidate: file:line, the change, the MECHANISM of the expected win,
   risk. NO edits in this phase.
2. SINGLE SERIAL APPLIER (owns the box — ONLY agent that benches, so zero contention): applies top
   candidates ONE AT A TIME → build (make USE_URING=yes MALLOC=jemalloc; rm .make-settings if it
   has fsanitize; verify --version jemalloc + .text ~4.36-4.38MB + distinct md5) → sanity-gated A/B
   vs the fork's FROZEN baseline binary → keep only CLEAN WIN or CLEAN-NEUTRAL-with-simpler-code,
   REVERT regressions. Structural edits get an ASAN churn pass. Returns kept edits + deltas +
   reverted list + any concern.
3. MAIN LOOP (me, on the pass's completion notification): commit kept edits to the fork's
   improve-dev branch, journal, launch next pass. If a hot-path win is PORTABLE (shared code across
   forks), queue a propagation pass to apply+validate it on the other forks.

## SANITY RULES (hard — user doctrine)
- jemalloc ONLY. Verify every binary: `--version` shows malloc=jemalloc-5.3.0; `.text` in the
  ~4,36x,xxx range (auto forks slightly higher); md5 distinct from baseline; number in sane range.
- SANITY-GATE every bench number. Nonsense (e.g. GET32 < 5.5M on this box) => DISCARD + re-bench;
  if persistently wrong, STOP, reread code/harness, fix, never reason from a bad number.
- 3+ reps interleaved, discard contended; keep only if delta beyond noise (>~2% win) OR
  flat-with-genuinely-simpler/less-code. NEVER commit a regression.
- Only touch improve-dev branches. Canonical branches are FROZEN. Push improve branches to GitHub
  after each accepted edit (recoverable across context loss).
- The three build traps caught this project: libc (deps/jemalloc skipped), identical-binary
  (committed change => stash no-op), ASAN-instrumented (.make-settings persists -fsanitize). Guard
  all three every build.

## Representative bench cells per fork (io4ex4 unless noted)
- 2s static: GET32, MIX32 (dispatch-bound, where overhead-shaves show); spot d512_19.
- 3s static: strict i3e3w2 MIX + a 512B/16KB send-bound cell.
- 2s auto: KNOB-OFF GET32/MIX32 (must equal static — hot path is shared) + knob-on boot smoke.
- 3s auto: KNOB-OFF strict MIX + smoke.
Baseline binary per fork = its improve-dev HEAD at loop start (frozen copy in selfimprove/base_<fork>).

## Region rotation (hot paths; cycle, re-read after a full sweep)
1 parse/multibulk (networking.c)  2 dispatch/routing (server.c processCommand + express)
3 exec slice (exSlice/exExecFake)  4 drain/reply (handleWorkerReplies + cdb)
5 teardown (freePendingCommand/reclaim)  6 reply serialize (writeToClient/_writevToClient)
7 SPSC (exQueuePush/PopBatch/flushExQueues)  8 spin/prefetch tails
9 fork-specific: auto=balancer/migration (control-plane, simplify not bench); 3s=wb slice/splice

## Cross-fork propagation
Most hot-path code is SHARED across forks (common base). A win validated on one fork should be
ported to the others where the region exists (build+smoke+quick-bench each). Journal per-fork.

## Journal: selfimprove/journal.md — append one block per pass:
`## PASS n | <fork> | region <k> | <UTC time>` then: candidates tried, KEPT (edit + delta + reps),
REVERTED (edit + why), commit sha, portable? Running tally at top.

## Orchestration
Notification-driven: each pass Workflow completes -> I commit+journal+launch next. Fallback
ScheduleWakeup (~1800s) guards a hung pass. Stop launching new passes once now >= deadline_epoch;
finish the in-flight pass, then produce a FINAL REPORT (selfimprove/FINAL_REPORT.md) summarizing
per-fork kept edits + cumulative deltas, and leave all improve branches pushed for user review.
DO NOT merge to canonical — user reviews on return.
