# t-flipdamp lane notes (THIS FILE IS MY MEMORY -- keep current)

## Assignment (owner, 2026-09-05 relaunch after 19:20 usage-limit kill)
Defect: `--flip-auto 1` (2s) lost 19.5% on multi-key 18:14 (MSET8+MGET8 1:1 p32, 512 conns) with
3 flips, 993 clients moved, target 18:14 unchanged. Do: (1) A/B matrix 3 regimes + pure-GET null,
same-binary null first; (2) if the guard is not enough, successor policy = cost gate + window/
variance + outcome loop, ONE feature file; (3) directed test + batteries + differ; (4) PRE/POST table.
Report commit hash + exact flags. Never merge into t-merge14.

## Box rules (non-negotiable)
Cores: physical 52-57 + siblings 180-185 only. Server 52,53,180,181; loadgen 54-57,182-185.
Ports 8220-8229. Gate: $SP/quiet.done exists AND older than 3 min (find -mmin +3) before make or
bench; ps/taskset intruder scan first. Kill by PID only. Pinned compile: taskset -c 52-57,180-185.
Scripts: scratch/lib.sh (geometry+gate), gatewait.sh, ab.sh, splits.sh, hold.sh, mk.sh, sk.sh.

## State reconstructed 2026-09-05 evening (transcript lost)
HEAD 66d4c13a3 (WIP salvage, unreviewed) on top of b5258d620 (WIP) on merge base e902c67d5.
build/tomokv (14:50) is NEWER than all sources (14:49) => binary == HEAD source. PRE binary =
/home/user/Projects/wt-flipdamp-base/build/tomokv (e902c67d5, built 12:04).

### What the fix already does (code comments are the evidence trail)
1. ROOT CAUSE (found by predecessor): issue_initial_jump divided each role's busy_ns by its OWN op
   counter; ex counts one op per SHARD TASK (7.576 per MGET8 command) so ex looked cheap and the
   model wanted io=82% -> flipped 5:3->7:1 (0.29M vs 0.95M) -> walked back = "3 flips, 993 clients,
   target unchanged". Fixed: demand share = busy-time share (command count cancels). Single-key is
   unaffected (1 command == 1 task) -- that is why the defect was 40x workload-dependent.
   => The owner's brief ("client-weight actuator, role actuator never fired") is the WRONG theory.
   flip_completed counted ROLE flips (a round trip); each role flip re-plans ALL client weights across
   surviving io threads (server.h ~900-950) which is why ~65% of connections move per flip.
2. pass_depth removed from the fingerprint trigger distance (actuator moves it: sweep-abandon law);
   still dumped for diagnosis (DEBUG FLIPCTL dist_parts).
3. Band quantum 1/sqrt(N) (estimator noise) instead of 4/N.
4. Model hold: 3-sample window of io_frac; hold (no flip) when equal_units==now or |mean-now|<=spread.
5. Null-maneuver outcome backoff: a maneuver ending on its origin doubles the confirming passes the
   responsible detector needs (cap = anchor learning windows); halves back when a maneuver moves.
6. Fingerprint shift needs shift_confirmations_ (>=2) consecutive out-of-band windows.
7. issue_flip refuses target == live split.
### Evidence on file ($SP)
- ab-base-mk-clean vs ab-fix-mk-clean (5:3, 8 cores, 12:28-13:32): BASE fa=1 always 2 flips ~440
  clients, -15%; FIX fa=1 3/6 held (rate ~ fa=0) and 3/6 round-tripped (-15%).
- ab-*-mk-r (15:16-15:22, co-tenancy, rates void): FIX fa=1 4/6 model holds, 2/6 round trips.
- hold-fix3-{1,2,3}: directed test 3/3 pass; hold-base2 fails (fingerprint re-trigger on base).
  BUT hold-fix3-3 shows rate_surge=1 + rate_collapse=1 during the constant-mix hold => 2 flips, 17
  transfers (test does not assert on the rate detector). null_maneuvers=3, model_holds=2.
### Open problem => successor policy needed
The 3-sample window still lets a biased-but-tight window pass (2/6 boots). Rate surge/collapse
triggers on a stationary paced load also start maneuvers. Each non-held maneuver = seek = 2-3 flips
+ 2 stabilised windows at a bad split (-15..-20% over a 20s cell).

## Plan
1. gatewait -> same-binary null (fix fa=0 vs fa=0) on mk -> rig noise.
2. splits.sh mk 1:3 2:2 3:1 (fa=0) -> true optimum on this rig.
3. Matrix: base0/base1/fix0/fix1 x {mk, sk1:1, sk9:1, get}, 20s cells, 3 rounds ABBA.
4. Successor policy in flipctl (variance-sized model window + cost gate in throughput space +
   outcome loop on the seek), re-run matrix, hold test, flip batteries, differ, PRE/POST table.

## Log
- 19:3x: resumed; box busy (owner memtier on 64-127 -> port 8034); quiet.done MISSING; scripts
  rewritten for new geometry; waiting on gate.
- 19:45 gate opened. Built guard binary copy -> $SP/fd-tomokv-guard (66d4c13a3). Wrote policy:
  src/core/flip_policy.h (pure: FlipDemandWindow Welford, flip_projected_rate = min(s/f,(N-s)/(1-f)),
  flip_choose_split sequential MOVE/HOLD/keep-sampling) + flipctl.cc decide_placement (saturation
  gate: both roles headroom > band => hold-unsaturated; cap = deferral/tick/2 readings) +
  seek_after_reading verify-or-revert + anchor() round_trips_/model_margin_ (x2 on round trip,
  /2 on delivered, cap where band*margin >= 1). Unit test extended (defect numbers). Commit: see git.
  Unit test caught: "optimum at the mean" is NOT a hold when the interval admits a paying split ->
  hold only when no split clears the bar optimistically.
- 19:52 matrix launched detached: $SP/fd-matrix.csv (30s cells, 3 rounds, arms pol0a pol0b pol1
  guard1 base1; wl mk sk1:1 sk9:1 get). Timelines: $SP/fd-tl-<arm>-<wl>-<round>.txt. Log fd-matrix.log.
- 19:58 mk rounds 1-2 (30s cells, 2:2 of 4 threads, 256 conns p32): pol1 = ZERO flips both cells
  (model hold at first reading => saturation gate: both roles had headroom > band => this rig is
  LOADGEN-BOUND for mk with 8 memtier HW threads vs 4 server HW threads). guard1 2 flips/363-372
  clients each cell; base1 2-3 flips/370-548 clients, one cell ended LIVE 3:1. Rates unusable:
  same-binary null pair differs 13% within a round (pol0a 447k vs pol0b 516k); box load 21, another
  lane on 48-50 (my L3 CCX). guard1 r2: p99 = 30015 ms = connections stalled the whole cell (rate
  184k). pol0b r2 (fa=0, no flips) p99 1003 ms -> 1 s stalls happen without flips too. Cause unknown;
  server logs clean. NEXT: kill matrix after mk r3; satprobe (find server-bound loadgen params);
  flipprobe (explicit FLIP cost/stall with memtier per-second lines); relaunch 60s cells with
  memtier output captured; rate verdict needs the owner's quiet box -- counters are the evidence here.
- io idle span = arm_blocked + submit_and_wait(1) only after a sweep found nothing => idle_ns is a
  fair "nothing to do" measure; the saturation gate is sound.
- 20:04 matrix mk (15 valid cells, 30s, 2:2/4 thr): pol0a 480k pol0b 514k (same-binary null 7%
  apart, 17% intra-arm spread) | pol1 394k (-21%) ZERO flips 4 trig 4 holds | guard1 281k, 6 flips
  1020 clients, 2 cells p99=30s STALL | base1 440k (-11%) 8 flips 1316 clients, twice ended live 3:1.
  16th row = artifact of editing ab.sh while running (bash re-read at shifted offset) -> NEVER edit a
  running script. Self-match trap hit once (pgrep -f pattern in my own cmdline + cwd check) -> use
  `pgrep -f` only from a shell whose cmdline does not contain the pattern (a script file).
- satprobe mk p32 c32 t8: 525k, server io=0.86 ex=0.935 busy, memtier 27% of 8 HW threads =>
  neither side CPU-saturated: closed loop is latency/wake-up bound. Saturation gate = "capacity
  model valid only when a role is CPU-saturated"; hold otherwise (comment fixed). pol0 cell with
  fixed parser: io 0.90 ex 0.97.
- OPEN: pol1 zero-flip loss (-8/-28/-31%, always the middle cell, after a stalled guard1 cell in
  the bad rounds). Test when gate reopens: diag1 (pol0/pol1 alternation 40s x2 + flipprobe) with
  per-second traces -> cellview.py (rate by controller phase).
- 20:04 gate CLOSED (owner measuring). gatewait running.
