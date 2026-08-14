---
name: thredis-pushed-2026-08-05
description: "PUSH MILESTONE: 269db1a37 is on GitHub as BOTH 2s-numa-stable-dev and the DEFAULT branch `stable` (forced, owner-waived NO-GO); gate scorecard 15/17 with all 5 remaining checks named + fix designs; amended cell-only revalidation protocol"
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

2026-08-05. The 27-commit LB/scram/scalability line was PUSHED, owner explicitly waiving the
GO-stamp rule for this once ("push after gate no matter result... too much commits").

## What is where

- GitHub `stable` (THE DEFAULT BRANCH): `7a11afb95 -> b6a427733 -> 269db1a37` — forced update, lease held.
  The old default was 2026-07-20-era; its one unique commit (reshard P0 livelock) is present in
  our line by patch-id, so nothing was lost.
- GitHub `2s-numa-stable-dev`: created at `b6a427733`.
- Local staging `stable-w`: `5ff1a884a..b6a427733`.
- The push chain is TWO-hop: mergew -> stable-w (local dir remote named "origin") -> GitHub.
  mergew can also push GitHub directly (`git@github.com:henrychen917/tomokv.git`, SSH works).

## Gate state at push (preflight13, binary sha 6eba479b)

15/17 suites PASS. The 5 remaining checks, each with a settled diagnosis:
1. busy-eval 8/20 — the scram's DESIGNED fast-RST vs a no-retry cell; cell now retries once
   (committed b6a427733), cell-only standalone validation still pending.
2+3. anti-thrash-p32 / long-hold-p32 at 4 flips — residual slow oscillation. Veto backoff
   (net-zero probes double the trigger sustain) halved 8->4 and slowed ~40s->~80s but did not
   quench. NEXT FIX: same-wave latch — after 2 net-zero probes, require |lr − lr_at_last_trigger|
   > gstep before another trigger (same wave suppressed forever, materially new state probes).
4. OPPOSITE-OPTIMUM "GET must reach io6" — STALE: full-populate moved the true GET optimum to
   io5ex3 (the hit-rate trap's own corollary); the controller landing io5 is CORRECT. Fix cell.
5. SHIFT-ioexit exit-slot-conns=NA — the INFO emitter's filter hides a drained growth slot's
   tombstone row (skips dead+empty); the check needs to see "slot 0 0". One-line emitter fix.

## Protocol amendment (owner)

A TEST-CELL defect against an unchanged binary: fix the cell, revalidate THAT CELL standalone,
commit — the green suites stand (the stamp is sha-matched to the BINARY; suites are the
instrument). A SERVER defect: full gate rerun. And the gate now CONTAINS every ad-hoc probe
(long-hold-p32, EXBOUND, listening-aware clientlb, port asserts, full-populate fills, fence
kill-retry) — no more parallel individual-test loops.

Related: [[thredis-wrong-two-quantities]], [[thredis-flip-test-window-and-drift]],
[[thredis-preflight-contract]] (the waiver was one-time, not a precedent).
