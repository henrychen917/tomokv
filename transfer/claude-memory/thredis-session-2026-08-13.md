---
name: thredis-session-2026-08-13
description: "Session 2026-08-13: cxnuma single-node flip regression FIXED+validated (14/14) + 2 obs hooks; per-node flip both-nodes-actuate proven, '2 6 6 2' divergence EPYC-gated; finalmerge (stable+cooldown+cxnuma+O1) built+sane, FULL GATE running, push-on-GO fast-forward."
metadata:
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Continuation of [[thredis-session-2026-08-12-close]]. Goal: final stable before the Saturday
professor meeting + EPYC move — every fork committed-to-stable or explicitly not-merged.

# cxnuma (#67) single-node flip regression — FIXED + VALIDATED
- Codex commit **4d9a13a98** "restore single-node flip compatibility": the regression was NOT my
  main-tail hypothesis. Real cause = cxnuma's multi-node concurrency protocols (migration-admission
  lock in tmFlipTryClaim, flatResizeAnyActive vs base flatResizePending, plan-after-lock, RESERVED
  mailbox) had leaked into the nnodes==1 path, changing WHICH 4Hz sample becomes an applied probe.
  Fix = explicit nnodes==1→base-ordering / nnodes>1→per-node split (subsumes my H1 fix into the
  multi-node branch).
- VALIDATED on a cooled, codex-quiet box: **controller_sweep 14/14**, AUTO==STATIC-p32 **0.11%**
  (was 9.27% FAIL), anti-thrash 0, long-hold PASS; **simnode2 multi-node PASS**.

# 2 observability hooks added to cxnuma (bit-identical, observability-only)
- **INFO** `tomokv_node_%d_io_live` = tm_node_iolive[n] (IO role), `_ex_live` = tm_node_wlive[n]
  (EX role — the node's live bucket-owning workers). Direct reads, no stride math (my first formula
  ex_per_node-io_live was WRONG; ex_per_node is a fixed addressing stride, codex flagged it). @442e80bd6.
- **DEBUG TOMO-NODEOF <key>** → node index via exIndexForKey()/ex_per_node (the real xxh64 routing).
  @12dbcdc9c. NOTE: DEBUG needs `--enable-debug-command local` at boot or it errors "not allowed".

# Per-node flip validation ($J/VALIDATION_SIMNODE2_FLIP.md, harness $J/simnode2_flip.sh + node_load.py)
- PROVEN: **both nodes' controllers actuate independently** — symmetric GET at 4 workers/node (1:1)
  drove BOTH node0 & node1 io2→io3, balanced per-node IO clients, GROW-FRONT on both nodes' iotids.
  node1 (non-semi-main) is NOT broken. Divergence observed once (node0 io2 / node1 io3).
- '2 6 6 2' (io4/ex4 = 16 workers) is **EPYC-GATED** on this 8-core box: 2:1 oversubscribed → caps
  ~440k ops/s → can't saturate → frozen controller correctly won't flip an idle server. At 4/node the
  range is io1↔io4 (Δ1, noisy). AND **IO-load is not node-confinable** (connections spread across both
  nodes' IO threads; only EX/worker work is key-pinned) — so selective per-node io-ward needs EPYC or
  IO-listener pinning. EPYC re-test: `IOB=4 EXB=4 SVRC=0-15 LDC=16-31 bash simnode2_flip.sh`.

# finalmerge = stable(119802b49) + cooldown + cxnuma(flip-fix+hooks) + O1(reshard) @ ccbb5da9f
- All merges clean (0 conflicts); built; **boot-sane** both node configs (DEBUG+INFO hooks live, no
  crash). 119802b49 IS an ancestor ⇒ **fast-forward push, no force**.
- **PUSHED to gh stable + 2s-numa-stable-dev @ 3b4715889** (2026-08-13; fast-forward 119802b49→3b4715889,
  no force). = ccbb5da9f (cxnuma+O1+cooldown, gated binary) + a docs-only commit (redis-heritage.md).
  Gate was NO-GO on ONLY the 3 box-noise p32 flip cells; owner WAIVED (3rd time) on strong evidence:
  14/14 correctness PASS, controller LANDS CORRECTLY (OPPOSITE-OPTIMUM "SET lands=[5 5]"=io5ex3,
  SHIFT-exward/EXBOUND/convergence PASS, all p1 cells PASS AUTO==STATIC-p1 0.04%). The p32 fails are
  measurement noise: AUTO==STATIC-p32 4.49% is throughput variance between the SAME io5ex3 config
  (auto landed at io5, proven by OPPOSITE-OPTIMUM); anti-thrash/long-hold = warm-box phantom flips.
  Hooks PROVEN inert single-node (INFO block nnodes>1-guarded, DEBUG-only) ⇒ ccbb5da9f flip==bf328085d;
  p32 cells are box-BIMODAL (bf328085d passed once, ccbb5da9f failed twice, same single-node code).
  Cooldown cools BEFORE controller_sweep but box re-warms DURING the 20-min sweep (p32 cells run late)
  — the p32 warm-box class is unfixable on 7700X; EPYC or per-cell cooldown needed.
- **Comparison sweep DONE (standalone).** bench_suite (codex-built, 16GB/64-cell) ABANDONED after 4
  successive box-incompat failures (runner unbound `local a=$1 b=${a}`; stale memtier-lifecycle patch
  anchor; ownership guard fail-closed on ROOT KERNEL THREADS pid1001 kworker; then memtier-JSON null
  parse + cell-1 boot INVALID) — codex fixed 3, I fixed the guard, but it never yielded a valid row.
  PIVOTED to a lean $J/cmp_sweep.sh — **INVALID / REJECTED by owner.** Two fatal errors: (1) ran TomoKV
  at FIXED static io4ex4 — CRIPPLES it (p1 wants io7ex1; TomoKV io7ex1 BEATS everyone at p1; must run
  AUTO/flip so it self-tunes per cell), so my p1 numbers (~0.6M) are WRONG; (2) only 36 cells = ~1% of
  the matrix + 20s/cell rushed. The p32-2-3x direction may survive but the run is not trustworthy.
  Artifact 91ee077d is WRONG-config — retract/redo. ** REDO with the real bench_suite (the full-matrix
  sweep the owner had me build) in AUTO mode, 300s cells (flip must converge), full axes
  (datasize 8/32/128/1024 × ratio 1:0/0:1/9:1/1:1 × pipe 1/4/16/32 × get_set+mget_mset × atomic on/off).**
  bench_suite auto-mode boots io1/ex7 + flip grows (tomokv.sh:242). Remaining execution bugs to squash
  on a tiny-DB/short debug config FIRST: cell-boot INVALID + memtier-JSON null parse (drivers/memtier.sh:326).
- Redis-heritage doc SHIPPED (in stable, $J/finalmerge/docs/redis-heritage.md): flatstore REPLACES the
  dict key store (not an index, unrelated to RDB); RDB kept+adapted to walk per-worker shard DBs.
- FUTURE: bench_suite worth debugging on EPYC for perf-counters + the true 16GB fixed-DB model + traces;
  garnet SKIPs (--threads option form); verify the Dfly 1KB-p32 anomaly with a Dfly-tuned config.

# cx102 (#102) — SHELVED (no measurable gain on a clean box)
Committed 4cea4674a (flat-reclaim owner self-skip). ASAN churn CLEAN (single+2-node, no UAF), correct.
A/B (fixed: exclusive box, instr/op, ABBAx4) shows NO write gain: GET-p32 CONTROL delta −1.07%
(consistent ⇒ code-LAYOUT offset from the 648B-larger binary = the real floor), so SET-p32 (raw
−0.83%) = +0.24% vs control and SET-p1 = +1.56% vs control — neutral-to-worse. Expected effect (skip
1/8 workers in a per-reclaim scan) is <0.1% instr/op BY CONSTRUCTION, below the layout floor. Per
[[user-hardcode-or-delete]]: shelved, NOT merged. Fork at $J/cx102writetax for EPYC re-measure; it
also CONFLICTS with cxnuma's per-node reclaim (needs re-apply). FIRST A/B was GARBAGE: ~14 orphaned
bin_* servers (binaries named bin_*, kill_srv ran pkill -x redis-server → never matched → pileup →
contention faked a 3% floor). The "renamed binary defeats pkill -x" trap ([[thredis-ab-harness-traps]])
— kill by real comm + `fuser -k PORT/tcp`.

# Comparison sweep COMPLETE (all-d32 scope, owner-ended 21:20) — see [[thredis-bench-suite-comparison]]
80 clean cells + torn matrix, 0 wedges. RESULTS: cross-system d32 TomoKV wins all 24 (p1 ~790k =
4.5-4.7x Redis, 1.05-1.07x dfly; p32 GET 8.22M = 1.84x dfly; SET p32 4.59M = 1.19x dfly the weak
spot); io/ex bathtub p1 opt io7 (monotonic), p32 GET opt io5 8.70M, p32 SET opt **io4 6.18M (+31%
over the io5 auto lands — landing-choice rider on #122)**; flip converges 10-115s = 1-4% of window;
mget-8: tk wins p1 (+10-21% dfly, 3.8-4.6x redis), dfly wins p32 (~12%); TORN probe: tomokv
atomic=off 24.35%, atomic=on **0/14.9M**, redis 0/19.1M, **dragonfly v1.39 defaults 0.74%
(65,279/8.86M — 2 zero-controls validate; re-verify stricter dfly modes before external use)**;
torn probe is coordination-shaped (8 hot keys) — redis tops its throughput there, regime not capacity.
DELIVERABLES: artifact 91ee077d REPLACED with real report (HTML, 6 sections, SVG bathtub); commit
**730dc029f** (detached on 3b4715889, docs-only, NOT pushed): README bench section + docs/bench/*.md
(6 files) + per-node/fence/observability changes INTEGRATED into owning README sections (owner:
integrate, don't append changelogs) + loadbalance-flip.md observability subsection. DEFERRED to
tomorrow: d128 io/ex curve (partial seg set aside SWEEP_d128_partial), d1024, zipf, ycsb, traces
(owner pulls), dfly strict-mode torn confirm. NEXT per owner plan: #122 fix session (300s static-io4
SET discriminator first), then EPYC transfer prep. Sweep data: $J/SWEEP (+SWEEP_v1_partial archive).

# Traps burned this session (see [[thredis-selfmatch-and-lock-traps]] update)
pkill -f self-match hit ~4×: a pattern in my own inline command, AND a pattern embedded in a
heredoc that landed in the LAUNCHER's argv → pkill SIGKILL'd my own shell (exit 144, empty output).
Use pkill -x (comm) or kill-by-PID; never pkill -f a pattern that appears in the caller's cmdline.
