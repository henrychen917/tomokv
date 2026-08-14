---
name: thredis-session-2026-08-12-close
description: "Session close 2026-08-12: docs pushed to gh stable; merge-cert 14/14 CLEAN (flip 'instability' was leftover-driver contamination, refuted); 2 P0 fixes on forks (O1 reshard forged-ack, cxnuma H1 deadlock); reshard⇄resize starvation found. Fork states + what each needs before merge."
metadata:
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Long overnight session. Everything below is FORK-ONLY unless it says pushed; owner makes the merges.

# SHIPPED
- **Docs → github `stable` + `2s-numa-stable-dev` @ 25b5cd6ac** (fast-forward from 181e1c8a1, no force).
  Exhaustive per-claim verification (~1,400 claims, granular fan-out + independent broad pass): docs
  ~99.6% accurate, io_uring-trap absent. 4 substantive + 6 nits applied; navigation wired (README ->
  7 subsystems + 40 mechanism docs, 200 links, 0 broken). Ledger: $J/DOC_FIX_LEDGER.md.
- **merge-cert (#118): PASS 14/14 on a proven-clean box.** The earlier "flip instability" (anti-thrash
  -p32=2, long-hold 0/18, baseline AUTO==STATIC 3.14M below its own floor) was ALL leftover-driver
  CONTAMINATION, not real — REFUTED. devmerge's frozen controller is conformant; clockdiet does NOT
  perturb it. The "clockdiet nudged the flip signal" hypothesis is dead.

# FORKS awaiting owner merge decision (base 57df9cd44 unless noted)
- **O1 / #120** ($J/cx120reshard, HEAD ~8894aa6d): reshard drain-fence GENERATIONLESS ack could forge a
  producer's drain after a fence-timeout abort (lost-write/UAF). FIXED: stamp each drain sentinel with
  its fence_gen (server.c:15646), ack only on match else count+log (server.c:22107), fence_stale_acks
  in INFO. Commits a51c7e465 + INFO. Regression reshard_suite 4/4 (2267 cutovers, 0 order violations).
  Discriminating "guard-fires" test DEFERRED — needs a DEBUG stale-sentinel inject hook (black-box
  timing can't force the abort-with-surviving-sentinel; see cx120reshard/O1_FINDINGS.md).
- **cxnuma / #67** ($J/cxnuma, HEAD 0b0c27e90, 8 commits): per-node control plane. Opus adversarial
  review: partitioning SAFE (cutover single-driver w/ serverAssert(iotid==0); resize/reclaim per-node;
  thread conservation ok). Found ONE P0 = H1 grow-back-flip <-> flat-resize DEADLOCK in the capstone;
  FIXED (reshardArmLocked:15888 — flip arms gate on flatResizeAnyActive not flatResizePending).
  Review: $J/CXNUMA_REVIEW.md. STILL NEEDS: rebuild+single-node tripwire (running at close) + simnode-2
  per-node-engagement validation before merge.
- **cx102 / #102** ($J/cx102writetax, 1 commit): write-tax census (468 lines) + one bit-identical
  reduction — worker-local reclaim skips re-checking the reclaiming worker as a reader of its own batch
  (it's quiescent then). REVIEWED plausible but it removes a term in the QSBR readiness path (UAF-class
  if the invariant ever breaks). NEEDS invariant re-review + A/B + ASAN/CHURN before merge.

# NEW pre-existing bug (NOT any of the above)
- **reshard⇄resize starvation** ($J/RESHARD_RESIZE_STARVATION.md): flatResizeCoordinate returns early
  while migration_active (global flag), so during ANY reshard EVERY worker's flatstore resize is
  blocked; a heavy insert flood during the migration window can't grow the table -> #117 table-full
  panic (size stays at initial 262144). P2 (migrations are short, but key-LB auto-reshard fires under
  load). Candidate fix: exempt non-migrating tables from the resize block, or per-pair not global.

# Box hygiene (cost hours this session — see [[thredis-one-server-one-bench]] update)
This session had accumulated DOZENS of leftover drivers/Monitors from earlier turns (night3.sh
launcher, devmerge_validate2.sh running its OWN sweeps on my port, soak loops, ugrep Monitors) that
silently contaminated every flip measurement. Swept + killed (by PID + process-group). Sweep for these
BEFORE any absolute-timing measurement; prove cleanliness with a loadavg sidecar, not a spot-check.

# Devmerge status — PUSHED to stable @ 119802b49 (2026-08-12)
devmerge (pendiet/clockdiet/pgo-harness/O4-guard) + docs are on gh/stable + gh/2s-numa-stable-dev
(fast-forward 25b5cd6ac -> 119802b49). CORRECTION to the overnight report: the "port-7976 comparison
campaign" I chased was a GHOST — it was the GATE'S OWN stress_reclaim suite (2 memtiers on 7976),
mis-read as external contamination (boxguard flags the gate's own multi-memtier suites). There was NO
external campaign. The gate's ONLY real failure was controller_sweep's 4 p32 flip cells; all 22
correctness suites PASS. Root cause: those cells measure per-role microseconds + absolute p32
throughput, and after ~90 min of heavy suites the box is WARM -> reads ~17% low / mis-flips at io5/io6
(in-gate FAIL vs 14/14 PASS on a fresh isolated box, boxguard clean). Frozen controller is NOT the bug.
Owner WAIVED the p32 cells (matching the 2026-08-05 precedent); I reconfirmed isolated controller_sweep
14/14 (AUTO==STATIC 0.63%, 0 boxguard) then pushed. P32 FIX: flip_cooldown (quiesce load<1.2 + thermal
settle) before controller_sweep + flip_updown in preflight.sh (committed to devmerge, validate via a
re-gate). Fork closeout in progress: cxnuma simnode-2, cx102 A/B, O1 decision.
Related: [[thredis-pernode-control-plane]], [[thredis-flip-controller-frozen]], [[thredis-preflight-contract]].
