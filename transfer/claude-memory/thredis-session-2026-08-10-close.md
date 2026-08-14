---
name: thredis-session-2026-08-10-close
description: "Session close 2026-08-10 overnight: #101 DELIVERED + pushed (dev @ab31c1bf7 gh) — wedge root-caused/fixed (gen-pins + budgeted reclaim, witnessed), window 512→64 = 1to1 4.8x crater kill, all mixed regimes beat pre-ownread, non-atomic grid zero regressions; 2 staged candidates (retdiet2 port, cxfront cold-split)"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**dev @ab31c1bf7 pushed to gh** (fast-forward from upstream base — gh dev had never advanced past
a176d1225; ancestry verified, nothing clobbered). Full story in
[[thredis-ownread-wedge-rootcause]]; report at `$J/MORNING_REPORT_2026-08-10.md`.

# Shipped (all on dev)
ownread replay 96102135d → cxdrain cd58e4377 (budget B) → cxpins f278f252a (gen-pins A) →
resolver gate ea52b765a → cxknobs 75a7cc2c0 (#111 CLOSED: knob_matrix 85 PASS/0 FAIL incl. 5 new
atomic cells, all inflight-drains-to-zero) → window default 64 f78b51409.

# The numbers that matter (fresh-boot cells, t8 c25 p32, both sides same night)
64-key: 1to1 781K (was 162K crater — 4.8x), 9to1 1.19M (+21%), 1111 1.48M (+30%), pure_mget +6%,
pure_mset −13% (window curve measured 64/128/256/512 → knob for write-heavy); 40s soak 782K clean.
2M: 1to1 +28%, 9to1 +10%. Non-atomic grid: zero regressions, mget8_p32 +5.9%, mset8_p32 +8.7%.
Correctness gauntlet all-zero ×4 (last at w64 where park paths pound).

# Staged candidates on gh (NOT on dev — owner review)
- `dev-retdiet-candidate` fe12aa48d: retdiet2 port on lifecycle-pin protocol (codex-cxretdiet,
  2 commits). Merged clean, builds, boots, wedge cell 798K (+2.2% vs dev). Gauntlet was running at
  close (result in `$J/gauntlet_retdiet.log`). STILL NEEDS: line review + ASAN churn
  ([[thredis-asan-repro-recipe]]) before dev — UAF territory (#102 lever, +3.8% claim).
- `dev-cxfront-candidate`: 3 of 4 cxfront cold-split commits (#116), UNMEASURED. 4th commit HELD —
  it cold-marks atomic window-park paths, rare at w512 but HOT at the new w64 default; re-split
  before judging.

# New reusable knowledge
- gdb on this box: ptrace_scope=1 blocks attach/gcore → run server as gdb child (batch) + external
  SIGTRAP; `server.clients` is a per-iotid ARRAY; `exec_tail` is a flexible array (`[0]` it).
- knob_matrix: TOMO_BIN env, verdicts in `$J/knob_matrix.out` not stdout.
- Gauntlet payoff cells MUST fresh-boot per cell (backlog poisons the next cell — apparatus fixed).
- The window is a first-order tunable for the atomic pipeline: pile depth ∝ window on hot sets and
  smaller windows keep the whole pipeline cache-hot even at 2M (512→64 won EVERYWHERE mixed).
- rc=0 without throughput = vacuous (re-confirmed the hard way).

# Open, ranked
1. retdiet candidate gate (review+ASAN) → dev if green.
2. cxfront measurement (perf topdown frontend% + quick-check) + re-split held commit.
3. Own-scan pile-walk redesign only if w512-class windows ever needed under same-key churn
   (per-client own-install key index design recorded in [[thredis-ownread-wedge-rootcause]]).
4. #112 re-measure post-resolver-work; then the standing queue (pureex scale, thread-naming,
   #115 uring u_io, flip residuals: warmup A-B-A, modal landing, zrange tie).

# STABLE PUSHED 2026-08-11 @09774330d (owner-waived)
gh 2s-numa-stable-dev 2f80ef045->09774330d AND default stable 6d19dc593->09774330d. Basis: 17/20
gate suites clean (incl. simnode2_features first run); all 7 failing cells triaged HARNESS-side
(4 stale MULTI/WATCH/EVAL contracts fixed, busy-eval proven 5/5=20/20 isolated => retries 3->5,
controller settle certification widened 10s->40s to span the documented oscillation period);
cmd_coverage rerun 0-fail before the push; feature_sweep + controller_sweep reruns were in flight
at push time (composite verdict lands after). RERUN RULE recorded in the preflight contract:
server change => full gate; harness fix => cell only. Day-2 additions on stable: tombstone
resurrection + expiry-index fixes, thread names, reorder time-aging (#87), TEN knobs deleted
(20-knob final surface: one key-LB / one client-LB / one flip knob per owner), symmetric
topology prefetch (0/1/2 with cross-node detect; simnode2-witnessed), simnode2_features gate
suite. IN FLIGHT at close: comm-tax agents (inline-ring 64B entries, inline-reply-in-CDB-line,
in-node prefetch fork) from the measured 400ns/cmd IO<->EX handoff decomposition (worker rig
10.5M/3.29 IPC vs real 2.0M/1.17; IO side weaker: rig IPC 2.29, p1 119K/io-thread) + the staged
IO census (per-role perf via thread names) + pure-IO rig refresh.

# COMPOSITE GATE VERDICT 2026-08-11 (FINAL): stable @09774330d PASSES the fixed harness 21/21
Main run 17 suites PASS + cell reruns per the owner rule: cmd_coverage PASS, feature_sweep PASS
(busy-eval 20/20 with retries 5), controller anti-thrash-p32/long-hold-p32 PASS with ZERO flips
under the 40s-certified settle (convergence 240s within the extended budget; AUTO==STATIC +0.85%)
— the owner's 'more run time' applied at the certification was exactly right; the old 2/10-flip
counts were mid-oscillation sampling of uncertified settle. atomic_correctness suite (promoted
3c) first scored run 14/14 PASS.

OPPOSITE-OPTIMUM: the last FAIL dissolved into TWO harness defects, zero controller defects
(owner's "sure u didn't catch it mid move?" was the thread that unravelled it):
1. MID-MOVE READ (owner called it): the cell scraped the last flip line the instant a 20s window
   ended — inside one probe period, 12x short of measured convergence. The "io6 landing" was a
   climb apex with rejection pending (its 6.55M ops = io4/5-mix; settled io6 measures 4.26M).
   Fix = certified read: 40s flip-quiet probe windows under sustained stimulus, then read.
2. STALE ORACLE: certified reads then showed io5 landings 3/3 — because the p32 SET curve
   INVERTED under the binary: interleaved A/B on stable @09774330d gives io5ex3 7.57-7.68M >
   io4ex4 7.46M (+3%) >> io6ex2 5.25M (-31%); the io4-best oracle predates ownread/window-64/
   prefetch/uring2. The m5 controller was finding the true optimum and being graded wrong for it.
   Second stale-oracle episode for this cell (GET io6->io5 2026-08-05). RULE now in the cell
   comment: consistent modal landing one step off expectation => re-measure the curve first.
Cell redesigned (86e05835b + ea7e661ed on dev): opposite REQUIRED ACTIONS — SET boots AT io5
optimum, must modal-HOLD (5->6 = -31% cliff); GET boots io4, must modal-CLIMB to 5-6; landing =
mode of <=3 certified landings, early-exit 2/2. Rerun on the identical binary: PASS (SET [5 5]
holds, GET [5 5] climbs). Controller correct in BOTH directions from BOTH boots.
FOLLOW-UP flagged: AUTO==STATIC-p32's static reference (io4) is a -3% soft reference now —
update to io5 in the next harness pass (its PASS stands under stated criterion).
[RESOLVED same night: 0ef10d559 — reference = best of static io4/io5, certified by preflight11.]

# STABLE PUSHED 2026-08-11 @843235366 (owner-directed, gate in flight — 09774330d precedent)
gh stable + 2s-numa-stable-dev + dev all 09774330d->843235366 (fast-forward). Content: the
flatstore insert-full P0 FIX (task #117: sentinel + quiesce-handshake wait + URGENT-first
coordinator + witnesses; satfill 20/20 with the race provoked 4x and absorbed 4x) + 5 harness
commits (satfill gate suite 3d per the new BUG-CATCHER RULE, OO certified-modal landing +
2026-08-11 re-measured oracle, AUTO==STATIC best-of-io4/io5 reference, gate hardening). Full
preflight (preflight11, staged sha 4a330b6db28c8a81) was RUNNING at push time — composite lands
when it finishes; any FAIL = fix-forward on stable, never silent. Caution noted: one codex agent
(ring recovery) alive during the gate ⇒ timing-marginal cells get quiet-box cell reruns before
being read.