---
name: thredis-main-blocked-module-gil
description: "docs/BUGS.md O — main deadlocks on the module GIL in afterSleep; my first fix REPRODUCED it (flag init 0 vs the boot lock); and uptime_in_seconds is NOT a main-liveness signal in this fork"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-03. The second defect under "memtier hangs in cycle 2", distinct from
[[thredis-soak-harness-truth]]'s N and it survived N's fix (run 6: `PASS=22 FAIL=1`).

## The GIL path is live at all times

This Redis 8 build ships **`vectorset` as a BUILT-IN module**, so `moduleCount()==1` with no
`--loadmodule` (confirmed: `MODULE LIST` → `name vectorset ver 1`). Upstream main therefore locks
and unlocks a process-global mutex **every event-loop iteration** for a module the workload never
calls. Removing that round trip is the perf change; the deadlock is a separate bug on the same lock.

## THE TRAP: the GIL starts LOCKED, AND MAIN IS THE OWNER

`moduleInitModulesSystem()` does `pthread_mutex_lock(&moduleGIL)` on main during init — *"Our
thread-safe contexts GIL must start with already locked"*. Nothing unlocks it before `aeMain`.
**Upstream's UNCONDITIONAL release at the tail of `beforeSleep` is what balances that boot lock on
iteration 1.** So any change that makes the release conditional MUST initialise its
"do we hold it?" flag to **1**, or iteration 1 skips the release and `afterSleep` re-locks a
non-recursive mutex main already owns → self-deadlock on the first pass, every boot.

I got this wrong (`static int main_holds_module_gil = 0`) and my fix for O reproduced O exactly.
Fixed `a137ce5cf`. Also: `moduleTryAcquireGIL()` must record the want, else a try-only module
starves forever once main stops handing the lock back by default.

## THE OTHER TRAP: uptime_in_seconds is NOT main-only here

I previously recorded "frozen `uptime_in_seconds` = dead main" as the detector. **That is FALSE in
this fork.** `afterSleepIO()` calls `updateCachedTime(1)` (`server.c:2962`) and is registered on
**every IO thread's** event loop (`server.c:17796`, `17851`). Measured 47 s of uptime over 45 s of
wall clock on a binary whose main was provably dead. Any probe keying off it is vacuous — which is
why `module_gil_pairing.sh` "passed" a deadlocked binary. See [[thredis-vacuous-validation-trap]].

**The real detector: the FRESH-CONNECTION hang rate.** Each IO thread has its own listener, so a
wedged thread keeps being handed new connections and answers none, while established connections on
surviving threads carry on — which is exactly why PING/SET/GET/INFO all report health. Rate is
~`1/io_threads`; run at `io=1` to attribute it to main unambiguously. Discriminates 25% (io=4) and
100% (io=1) against 0% healthy.

## Status: O is STILL OPEN

Stacks are real (5 samples, 2 processes, identical PC: `__lll_lock_wait · pthread_mutex_lock ·
afterSleep+0x15e`, and `+345` is the only `pthread_mutex_lock` in that function). Mechanism
identified but never reproduced: `ProcessingEventsWhileBlocked` is a plain **global** `int`
(`networking.c:43`) in a one-event-loop-per-IO-thread server; `rdb.c:3618` calls
`processEventsWhileBlocked()` off-main while `script.c:159` guards the same call with
`iotid == 0`. The fix pairs on main's own record so a racing global cannot skip the release.

The rewritten probe does **not** reproduce the original race (pre-fix binary passes 30 reloads ×
120k keys). So the fix is correct-by-construction and now known not to be harmful, but **uncredited
against a real repro**.

**Soak 8 (2026-08-03, binary `8360096ea`/`0071ea213bdc`) is the first numa2 pass**: `PASS=23
FAIL=0` across both nodes, ~3.2B commands, 0 crash markers, RSS *falling* on both, and every
engagement gate open (flips, bucket moves, FLATSTORE rebuilds, churn, 21 command families). Cycle 2
had failed in runs 2/4/5/6; run 6 already carried N's fix and still failed, so the delta is the
corrected O fix + GIL skip + the nested-path fix.

**Still not marked FIXED.** One pass against a 4/4 prior failure rate is evidence, not proof, and
there is no direct reproduction to test. Wants a second numa2 run before `BUGS.md` flips to FIXED.
Also a third defect was in my own fix: `beforeSleep`'s nested early-return released the GIL *during*
nested command processing (the flag is 1 there, inherited from the outer loop, not 0 as I claimed) —
removed; tail-only pairing already closes O by itself.

Related: [[thredis-soak-harness-truth]], [[thredis-vacuous-validation-trap]], [[thredis-ab-harness-traps]].
