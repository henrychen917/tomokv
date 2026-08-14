---
name: thredis-endgame-two-versions
description: "Target end-state (user 2026-07-03): exactly TWO versions — one 2s, one 3s — each runtime-selectable epoll or DEEPLY-integrated io_uring; knob surface collapsed"
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

User's consolidation decision (2026-07-03): ship exactly **two versions** — one 2s, one 3s — each offering **epoll OR deeply-integrated io_uring** as the reply/IO backend. Everything else is archival (old/, strict non-pool, sendonly, v3/dev/stable/merge).

**v13 BRANCH SPLIT (2026-07-03):** because the 3-audit cleanup (25 HIGH integration findings + 26 hot-path shaves + deep-uring) is huge/destabilizing, the user asked to fork **v13** for the churn and FREEZE the paper-validated versions as fallback:
- **FROZEN fallback (paper/shipping):** `/shared/Projects/THredis-v12` branch `2stage-io-ex-uring` (HEAD 4af468309) + `/shared/Projects/THredis-strict-pool` branch `3stage-ifid-ex-wb-pool` (HEAD 7295362ff). Left pristine — do NOT churn these.
- **v13 dev worktrees (ALL new edits land here):** `/shared/Projects/THredis-v13-2s` branch `v13-2s` (from 2stage HEAD) + `/shared/Projects/THredis-v13-3s` branch `v13-3s` (from 3stage HEAD). First commit e198ef44e(3s)/07338737f(2s) = pad per-thread client arrays + FLUSHDB shard fix. Separate build paths → building v13 does NOT disturb benches using the canonical binaries. Both are worktrees of the shared /shared/Projects/THredis .git. Old /home/henry worktree pointers pruned.
- Fix plan: `overnight_sweep/hotpath_fix_plan.md` (4 batches). Reports: `integration_audit.md`, `hotpath_fix_plan.md`.

**Why:** [[thredis-canonical-forks-and-dfly-port]] already made these canonical; the knob-retirement study (overnight_sweep/knobretire.tsv) exists to hardwire always-good opts and drop dead ones so the knob surface collapses to genuine choices (thread split, epoll-vs-uring, and the few workload-dependent gates).

**"Deeply integrated io_uring" means** (from the kernel-scan + uring-send-fix analyses): the current reply-send overlay is NAIVE (plain ring, no SINGLE_ISSUER/COOP_TASKRUN/DEFER_TASKRUN, no io_uring_register_ring_fd, no registered files/buffers, per-send submits) and measures −4..−9% on loopback. Deep = ring-per-thread + DeferTR/SingleIssuer (EXCEPT strict-WB rings — DeferTR documented to stall there), register_ring_fd, batched submits per drain pass, registered files, SEND_ZC+registered buffers ≥1KiB, multishot recv (exists, v12-G) — per Jasny VLDB'26 this is the neutral→2x difference, payoff regime = real NIC.

**How to apply:** all new opts/fixes land on BOTH forks; negative knobs get an overhead-reduction pass + re-measure BEFORE being ruled out (user directive); per-stage prefetch verdicts (fc/argv/cmd/keyobj/hash/entry/value + io fc/reply) decide which stage knobs survive. Early retirement-study finding: the prefetch adaptive gate default (8M keys) is too conservative — 6M×512B (DRAM-bound) already gains +12% on 1:9 with the gate forced open.
