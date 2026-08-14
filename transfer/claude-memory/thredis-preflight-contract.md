---
name: thredis-preflight-contract
description: USER RULE — tools/preflight/preflight.sh is the mandatory per-version stress bench; GO stamp required before any push or comparison benchmark
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**USER RULE (2026-07-26): every version runs the preflight before it counts.** `tools/preflight/
preflight.sh <binary>` (in-repo since `24d05ad14` on 2s-numa-scriptfence-dev) is THE stress bench
for every version: one command, one GO/NO-GO. A push to the canonical branch and ANY full
comparison benchmark require a GO on the exact binary; `comp_inter.sh` enforces the stamp
mechanically (sha-matched, <24h, else refuses to start). `SMOKE=1` for a ~20-min pass.

**Why:** the week's history — stale binaries measured as new, sweeps on the wrong build, void
campaigns, harness misreads — all become structurally impossible when the gate is enforced rather
than remembered.

**How to apply:** after building any candidate: run preflight (SMOKE for iteration, full before
push/sweep); on NO-GO fix before proceeding; SUSPECT = stop and look (sanity-gate rule), never
average away; baselines update only via UPDATE_BASELINES=1. History ledger:
`preflight_history.tsv` + archived reports keyed by sha — check it when comparing versions.

Suites: knob matrix, FLATSTORE/QSBR correctness, numa=2, fence battery, feature sweep (oracle
equivalence vs stock Redis), controller conformance (SHIFT/ENVELOPE/NOREG/AUTO==STATIC,
settle-first, anti-thrash, client+key+flip LB), command sweep (every dispatch class × pipe{1,32}
vs baselines), bounded stress. feature/controller/command suites land from authoring workflows
wf_f3a641e3/wf_b7a6d084/wf_75c85947 + the settle-first revision. See [[thredis-epoch-fence-status]],
[[thredis-ab-harness-traps]].


## TIERED 2026-08-09 (owner): full gate is for STABLE only; dev pushes are lighter

Owner: "push to dev branch after each section" + "only run full gate when pushing to stable. just
check mechanism actually works and regression for dev branch."

**DEV push gate** (per section): (1) the mechanism PROVABLY fired — gate-opened counters, battery,
or the section's discriminating cells, on the topic tree the queue built and boot-tested; (2) no
regression on the section's regression cells. Merge into `2s-numa-stable-dev`, push to GitHub
(`gh` remote in stable-w2 — direct, bypasses the stale two-hop through stable-w).

**Merged-tree caveat**: merges are pushed UNBUILT (compiling mid-queue voids bench cells — recorded
failure). Every merge commit says so. As soon as the box frees (FINISHQUEUE_DONE), the merged dev
head gets: build + control-armed boot test + notifyguard 11/11 + the 8-cell quick-check + the
MULTI-under-atomic probe. Failure ⇒ fix-forward on dev, never silent.

**STABLE push**: full preflight GO stamp, unchanged.

Mechanics: `tmp/push_section.sh <name> <branch...>` — refuses on conflict, notifyguard-gates the
merged tree, pushes dev + topic branches. Conflicted merges go to a Codex agent with semantic
instructions, then re-gate. The baseline merge (T6 MULTI/EVAL dev × atomics ship line) conflicted in
db.c/multi.c/networking.c/server.h — both features must survive; MULTI-under-atomic interaction is
the flagged open question.

**RERUN RULE (owner, 2026-08-11): server code change => rerun the ENTIRE gate; harness-only bug
(stale contract cell, suite plumbing) => rerun ONLY that cell/suite standalone and composite the
verdict with the surviving run. The gate stamp names the binary sha; a harness fix does not change
the binary, so the other suites' results remain valid for it.**

**SMALL-IMPORTANT-FIX TIER (owner, 2026-08-11): "If it's small important bug fix just check it's
fixed, run a quick regression feature check, then push."** A small-but-important fix does NOT wait
for the multi-hour full gate before the stable push. The push gate for that tier is three fast
checks: (1) FIXED — the bug's own repro/promoted suite passes WITH its witness engaged (never a
vacuous pass); (2) QUICK REGRESSION — the 8-cell quick-check ([[thredis-quickcheck-protocol]]:
p32/p1 x GET/SET at io4ex4 & io7ex1, static, ops/s); (3) QUICK FEATURE CHECK — a fast correctness
pass over the touched subsystem plus basics (atomic_correctness / cmd_coverage, or SMOKE=1
preflight). Then push. The full gate still runs ASYNC when convenient — comparison benchmarks
still require a <24h GO stamp (comp_inter enforces it), so the async full run is what mints that.
First application 2026-08-11: flatstore insert-full fix (satfill 20/20 + witness = FIXED) pushed
@843235366 with the full gate backfilling in flight.

**BUG-CATCHER RULE (owner, 2026-08-11): "if a harness catches a bug add it to gate."** Any ad-hoc
job harness whose run exposes a real server bug gets promoted into a checked-in preflight suite —
same provocation, panic/integrity detection, and (post-fix) the fix's witness counters reported so
the provocation is provably reaching the mechanism. Precedents: atomic_correctness.sh (3c, from
the atomic gauntlet), simnode2_features.sh (3b), and satfill_stress.sh (3d, 8d6dc362f — the 40M
saturating-fill battery leg that caught the flatstore insert-full P0, task #117). **How to apply:**
when a battery/repro FAILs on a server defect, before closing the bug: extract the provoking leg
into tools/preflight/<name>.sh (exclusive port per #73, unique staged comm name, TOMO_BIN/
TOMO_RESULT_FILE contract), register it in preflight.sh, smoke-prove its mechanics, and make the
bug's fix validation run through THAT suite so gate and validation share one apparatus.
