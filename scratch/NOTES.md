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
- 20:46-20:55 diag2 (gate-then-run): pol0 470/479/478k vs pol1 502/478/493k (+3%, ZERO flips in 3/3,
  6 triggers all held) => the earlier -20% was rig noise/ordering, per-phase means flat.
  flipprobe (explicit 2:2->3:1->2:2 under mk): pol 386k mean, base 387k; 3:1 runs 180-230k vs
  480-520k at 2:2 (-60%); the flip transient is ONE second each way; 360-384 clients per round
  trip. => cost of a move = time at the wrong split, not the flip mechanics.
  BIAS FOUND: model_io_frac 0.66-0.73 with headroom_ex 0.47-0.75 on a workload whose busy shares
  are io 0.87/ex 0.97: sample_role_demand's spin correction busy*(1-spins/iterations) treated an
  empty spin pass like a task batch (ex loop enters the busy span every pass, spins outside it).
  The saturation gate held ONLY because the same wrong number inflated ex headroom; the model would
  have projected 3:1 +35%. FIX (4d8261d99): ex loop books an empty pass (did==0) as idle via a local
  pass_ns (monotone counters, 1 branch); controller uses raw busy/idle; ThreadMeasure = ops,busy,idle.
  guard binary stall (p99 30s in 2/3 mk cells) NOT reproduced on base or policy flip probes.
- 20:56 final.sh launched via gaterun: matrix2 (pol0a pol0b pol1 base1 x mk sk1:1 sk9:1 get, 40s x3)
  -> hold x2 pol + base -> batteries (8 srv threads 52-55+sib, 6:2) -> modes -> differ. Logs fd-final.log.
- 21:04 COORDINATOR: no per-cell reports (each wake costs the shared budget); ONE message at the end
  with full PRE/POST matrix (rate, flips, clients moved, p99 per regime) + verdict + commit hash.
  Owner holds the box marker ~1 h (acceptance window). final.sh aborted on the marker at mk r3
  (10 mk rows). Continuation = finalw.sh (pid 1929685, via chain.sh): PAUSES on the marker, resumes;
  runs missing rounds (ROUND_OFFSET, abw.sh), hold x3, batteries, modes, differ, report.py ->
  $SP/fd-report.html, touches fd-final2.done. Monitor b17mdlkwl notifies once (done or pid gone).
  matrix2 mk so far: OFF 504/498/510/517/521/524k; POST 488/498k (0 flips, 4 triggers held);
  PRE 460/435k (2+4 flips, 371+660 clients). If killed: rerun `scratch/finalw.sh` (idempotent),
  then publish fd-report.html as the artifact and send the single report message.

## 2026-09-06 night: VERIFICATION lane (owner: verification only, no actuator redesign)
State at resume 00:29: HEAD 4e8edf37a, tree clean, box gate CLOSED (quiet.done missing, load 40,
other lanes on 64-127 + a tomokv-post on 8260). Nothing of mine was running.

### What the killed session left behind (read from files, not memory)
- fd-matrix2.csv had ONLY the mk regime: finalw.sh line 11 counted rows with
  `grep -c ",$wl," || echo 0`, and grep -c prints "0" AND exits 1 on no match, so the substitution
  produced "0\n0" and the arithmetic died -- sk1:1, sk9:1 and get were silently skipped. FIXED
  (awk over the CSV shape). LAW for this harness: never count with `grep -c || echo 0`.
- report.py read only fd-final.log while finalw.sh logged to fd-final2.log -> "0 hold lines,
  0 battery lines, 0 differ lines" in the report. FIXED (reads the whole chain).
- differ was run as `differ_gate.sh ... 2:2`; its sort suite REQUIRES --shards 16 --ratio 6:2, so
  4 of the 4 "failures" were my invocation (pass=164 fail=4, all four `differ sort`). Re-run at 6:2.
- `--thread-mode 1s --flip-auto 1` is REFUSED by config (flip needs 2s). The mode row has to be
  1s-plain + 2s-with-flip-auto, not the combination.

### THE REAL FINDING: tests/flipctl.py (a GATE row) fails on this branch
Rail anchor 1:7 on 8 threads. DEBUG FLIPCTL: model_io_frac=0.0061, headroom_io=0.994,
headroom_ex=0.0000, origin_rate=4898.601, anchor_rate=6000.916, boot_rate_slope=0.0229 against its
own threshold 0.0297. So: (a) the driver is 3 connections of BITCOUNT over 4 MB bitmaps -- ex IS
saturated and io IS idle, the saturation gate opened correctly and work conservation really does
rate 1:7 at 3.5x; (b) the +22.5% that CONFIRMED the move was the driver's own ramp, still trending
under the deferral threshold. Base does not rail because it random-walks with halving steps and
settles on the best of several readings; my verify-or-revert takes ONE probe and compares it to a
single pre-flip reading.
FIX (4802ba52d): Measuring never moves the split, so its readings are readings of the ORIGIN.
Bracket them (min/max) and floor every band of the maneuver at 2x that spread -- the same
2x-observed-jitter convention as band_, the signature band and the rate band. Ramping driver =>
floor 0.40, the ramp's 0.225 confirms nothing, seek reverts to 6:2, anchors off-rail. Still
baseline => floor ~0, nothing changes. Pure helper flip_baseline_band() + unit rows; DEBUG FLIPCTL
dumps origin_rate_readings/min/max/baseline_band.
NOTE the binary changed => matrix2 rows are a different server. Kept as fd-matrix2-prev.csv; the
report reads fd-matrix3.csv.

### Tonight's chain: scratch/ver.sh (detached, pid in $SP/fd-ver.pid, log fd-ver.log)
Pauses on the box marker at every step, skips any step whose output is on file, touches
$SP/fd-ver.done at the end. S1 build+unit, S2 flipctl.py base x2 vs fix x2, S3 matrix3
(mk/sk1:1/sk9:1/get x 3 rounds x pol0a/pol0b/pol1/base1, 40 s), S4 hold test, S5 NON-VACUITY
(boot at 3:1 -- ~190k vs ~500k at 2:2 -- and require fa=1 to still move; fa=0 must not),
S6 instr/op + cycles/op at a matched rate via memtier --rate-limiting (base fa0 = hot path,
fix fa0, fix fa1 = always-on cost), S7 batteries 2s + fused both atomic, S8 differ at 6:2,
S9 report. Re-running `scratch/ver.sh` after any kill resumes it.

### RESULTS 2026-09-06 (ver.sh 00:43 -> 04:35, box marker held for ~100 of 230 min)
Binaries: fix sha 7c78940416c87e24 (build 00:57), base sha 692984a8c786998b (e902c67d5).
MATRIX3 (4 regimes x 3 rounds x 4 arms, 40 s cells, ABBA), ops/s mean | flips | clients | p99 med:
  mk     OFF 522k/520k (floor 3.2%) | POST 520k -0.3% 0 flips 4 trig 4 holds p99 63 | PRE 475k -8.9% 7 flips 1464 p99 80
  sk1:1  OFF 5175k/5150k (3.2%)     | POST 5103k -1.2% 2 flips 1 rt p99 3.1        | PRE 4508k -12.7% 12 flips 2052 p99 8.8
  sk9:1  OFF 5101k/5114k (0.4%)     | POST 5125k +0.3% 0 flips 4 holds p99 3.5     | PRE 4390k -14.1% 12 flips 2072 p99 6.5
  get    OFF 5303k/5297k (0.9%)     | POST 5308k +0.1% 0 flips 3 holds p99 3.8     | PRE 4818k  -9.1% 10 flips 1720 p99 5.4
THRASH (flips AFTER first anchor): POST 0 in all 4 regimes; PRE 1/6/5/4 (mk/sk1:1/sk9:1/get).
The single POST move: sk1:1 round 3 -- moved, did not deliver, reverted, round_trips=1, margin 1->2.
NON-VACUITY (boot at 3:1, mk, 60 s): fa=0 base 245k / fix 236k, live 3:1. fa=1 base 307k, 2 flips,
293 clients, ended STILL MANEUVERING at live 3:1 (round trip). fa=1 fix 442k, ONE flip, 154 clients,
anchored 2:2 at anchor_rate 516k and held; its second trigger (the rate surge its own flip caused)
was held as hold-unsaturated. Reference fix at 2:2 fa=0 = 530k.
GATE ROW tests/flipctl.py: PRE-FIX policy binary FAILED (rail 1:7). base 2/2 PASS, fix 2/2 PASS,
all four anchored off-rail at 6:2 on a 6000 ops/s driver.
INSTR/OP at matched rate (307.24k +-0.02% all six cells, 35 s perf window, mk 2:2):
  base fa0 32449 instr/op 26317 cyc/op | fix fa0 32025 (-1.31%) 26381 | fix fa1 32423 (+1.24% vs fix fa0) 26491
  same-arm spread 0.42-0.49%, so hot path is unchanged-to-cheaper and the always-on controller is
  +1.2% instr / +0.4% cycles -- inside the 3% budget.
HOLD directed test: pol 2/2 PASS (0 flips, 0 transfers); base FAILS (1 flip, live 3:1).
BATTERIES: flip/flip_under_load/flip_ttl PASS; fused s6/multi_exec/edgeproto/atomfix PASS both
atomic; spinprobe + idle-ceiling PASS 2s, 1s(atomic 0/1) and on BASE (ver2.sh -- spinprobe takes the
server PID, gate.sh passes $SRV; ver.sh had handed it the binary path).
MODES: 1s refuses --flip-auto 1 by config; 2s boots awaiting-load-stability.
DIFFER: 168/168 at --ratio 6:2 (the sort suite REQUIRES 6:2 + --shards 16; last night's 4 "fails"
were the 2:2 invocation).
Artifact: https://claude.ai/code/artifact/f01d7b82-5685-4f10-bf3f-e89010857b35

## 2026-09-06 day: ACTUATOR REDESIGN lane (owner: "be innovative about flip arithmetic and signals")
Base: d84031d2f (guard verified; do not re-measure). Build dir per arm: guard binary copied to
$SP/fd-tomokv-guard-d84031d2f (sha 7c78940416c87e24) BEFORE the first make; base = wt-flipdamp-base
(692984a8c786998b). Box marker MISSING at 09:10-09:22 (owner gate until ~09:40): design + code first.

### THE SIGNAL DEFECT (from the guard night's own lbsignals snapshots, sk1:1 r3, 40 s window)
  thread 0 io: busy 16.36 s + idle 0.17 s = 16.53 s booked of cpu_ns 39.92 s  -> 23.5 s UNBOOKED
  thread 3 io: busy 22.24 s + idle 2.40 s = 24.64 s booked of 40.02 s          -> 15.4 s UNBOOKED
  thread 1 ex: 25.62 + 2.56 = 28.19 of 39.99; thread 2 ex: 33.25 + 1.76 = 35.01 of 39.98
  mk r1:       io 27.6+3.5 = 31.1 of 38.1 (7 s unbooked); ex 38.7+1.2 = 39.9 of 40.0 (complete)
The io loop's busy Span closes BEFORE ring_.submit_and_reap(): the io_uring_enter syscall -- the
kernel doing the TCP send/recv, which IS io work -- is booked as neither busy nor idle. The share
busy_io/(busy_io+busy_ex) therefore read io = 0.32 on sk1:1 (headrooms 0.5%/3%, i.e. both roles
saturated => the true work share is ~0.51). R(1)=min(1/.32, 3/.68)=3.13 > R(2)=2.94 => the model
moved 2:2 -> 1:3, measured 2.45M vs 5.12M (-52%), reverted: the guard's ONE round trip. mk read
0.41 for a 0.477 workload (same direction, smaller: fewer syscalls per busy second).
FIX (signal): work = wall - idle. idle_ns is the one quantity both loops book faithfully (io: the
blocked wait after an empty sweep; ex: empty passes + blocked wait, since 4d8261d99). wall = the
controller's own tick clock (now_ms delta) x threads of the role. No hot-path change at all.
  sk1:1: io 2x(40-1.29)=77.4, ex 2x(40-2.16)=75.7 -> f=0.506 -> HOLD.  mk: f=0.472 -> HOLD.
headroom := idle/wall (was idle/(busy+idle), inflated 2.4x for io thread 0).

### DESIGN (one page): cost gate + variance window + outcome loop, all in src/core/flip_policy.h
UNITS: commands (delivered work), seconds (tick clock), clients. R0 = origin stabilized rate [cmd/s].
g = projected relative gain of the argmax split (model R(s)=min(s/f,(N-s)/(1-f)); the step IS the
distance: jump to the argmax). kappa = the model's calibration (below). All terms are measured or
derived from the controller's own mechanics; no machine constants, no new knobs.
1. COST GATE -- a move must pay for itself within the stationarity the workload has demonstrated.
   T_stat  = now - stationary_since  (boot: first non-idle tick; change trigger: the trigger)
   T_black = T_flip + T_settle + (n_t - 1) T_read   [blind time before the outcome can be judged]
             T_flip measured per flip (issue -> Idle, tick-quantized; first flip: 1 tick),
             T_settle = 3 ticks (window reset + 2 sub-windows = the controller's reading mechanics),
             T_read = 1 tick per extra stabilized reading.
   C_xfer  = c_client x n_pred      [commands]
             c_client = sum(lost commands) / sum(clients moved) over every flip so far
               lost = R_before x dt_flip - commands served in dt_flip  (measured, clamped >= 0)
             n_pred = clients x |dio| / max(io0, io1) x rho, rho = sum(actual moved)/sum(naive)
               (the weighted re-plan reshuffles more than the converted threads' clients)
   P_miss  = (misses + 1) / (moves + 2)           [Laplace; no prior constant]
   benefit = kappa g_low x R0 x (T_stat - T_black)  [gain credited only after verification]
   cost    = margin x [ C_xfer (1 + P_miss) + P_miss x kappa g_mean x R0 x T_black ]
             (the revert with probability P_miss; a wrong move loses during the blackout about
              what a right one would have gained)
   MOVE iff benefit > cost AND kappa g_low > band x margin (the noise bar, kept: an unverifiable
   gain cannot pay). Else keep sampling (T_stat grows, the interval tightens) until the reading cap
   -> "hold-cost". First flip: c_client unknown = 0 (the flip IS the measurement; charged through
   the blackout term only).
2. WINDOW from VARIANCE -- sigma = relative stdev of the origin's Measuring readings (Welford,
   n_o >= 3). Planned target readings n_t = ceil(1 / ((kappa g_mean / 4 sigma)^2 - 1/n_o)); a
   non-positive bracket means the origin is not yet measured precisely enough to verify a gain this
   small -> keep sampling the origin. Threshold after k target readings:
   theta_k = max(2 sigma sqrt(1/n_o + 1/k), baseline bracket 2(max-min)/mid, typed band).
   Sequential at the target: accept when d_k > theta_k (early or at n_t), reject early when
   d_k < -theta_k (never sit at a clearly worse split), at k = n_t accept iff d > theta.
3. OUTCOME LOOP -- every move is a hypothesis (predicted kappa g_mean, planned n_t).
   hit  -> anchor at target; margin = max(1, margin/2); record delivered/predicted.
   miss -> flip back; margin x2 (cap where band x margin >= 1); misses++; delivered := 0.
   invalidated: after the return flip, if the origin no longer reads R0 within theta the baseline
   moved during the maneuver -- the test was voided, not failed: margin/misses untouched, counted
   as invalidated_maneuvers (the guard doubled the bar on these too).
   kappa = (sum delivered+ + gbar) / (sum predicted + gbar), gbar = mean predicted gain over moves:
   the model starts with the credence of exactly one delivered move of its own average size and
   earns or loses it; one miss halves every future projection (the bar doubles in effect), a hit
   restores it; kappa <= 1 (over-delivery never buys credit). Magnitude, where the margin is sign.
WHAT EACH REPLACES IN flipctl.cc: sample_role_demand busy share -> (wall-idle) share + idle/wall
headroom; decide_placement gains the cost gate + verify-window feasibility (decisions hold-cost,
hold-unverifiable); WaitingFlip measures the flip (lost, moved, duration) -> FlipCostModel;
seek_after_reading: one reading -> sequential Welford verification + outcome; anchor(): miss vs
invalidated finalization; report/debug/INFO: new fields; DEBUG FLIPCTL seek <io> [force] and
cost <cmds/client> are the directed-test hooks (cold, debug-gated). Knobs: none added.
