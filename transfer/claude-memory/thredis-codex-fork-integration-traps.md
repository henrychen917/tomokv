---
name: thredis-codex-fork-integration-traps
description: "Integrating Codex forks — boot-test FIRST, and a fork can silently revert shipped fixes (only the full gate catches it)"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Two fork-integration traps that each cost real time on 2026-08-06 (the 5-fork cross-shard batch). Both follow from [[thredis-codex-first-delegation]]: **Codex never runs the server**, so its output is *compile-clean but never executed*.

**1. BOOT-TEST the merged binary before cmd_coverage.** The MULTI/EXEC fork (`multi`) shipped a boot **segfault** — `createClient` read `c->tomo_local_worker` in `selectDb` (to pick a per-worker shard DB) *before* initializing it, so scriptingInit's script client indexed `server.exThreads[garbage]` OOB. cmd_coverage's "boot timeout" is the symptom; the real signal is a bare `redis-server ... ping` boot. **Rule: after every merge, `boot + PING + one smoke command` BEFORE the ~2-min cmd_coverage run.** A `lua_gc` frame in the crash is a red herring — it's the crash reporter's INFO call hitting an uninitialized Lua state; read the FIRST (innermost real) frame via `gdb -batch -ex run -ex bt`.

**Why:** the fix is one line (`c->tomo_local_worker = -1;` before `selectDb`). Diagnosing it via cmd_coverage's opaque "boot timeout" wastes a coverage cycle each time.

**2. A fork can silently REVERT shipped work — only the full preflight catches it.** `multi`'s `script.c` reverted the #81 slow-script listener-scram fence + made `processEventsWhileBlocked` unconditional (undoing bug-O's no-PEWB-on-non-main). Individual fast-path A/B gates (GET/SET p32) were all FLAT — they do NOT exercise scripts. cmd_coverage PASSED — it doesn't stress slow scripts. Only `feature_sweep`'s `busy-eval-concurrent-set` (17/20, the [[thredis-main-blocked-module-gil]] class) exposed it. **Rule: a fork that touches an area with a shipped fix (scripts, fence, lifecycle) needs the FULL preflight before you trust it — the cheap per-fork gates are blind to reverts.** multi was excluded from the batch; its T6 keyed-script routing must be layered *on top of* the fence, not replace it.

**3. New knob ⇒ register it in `knob_matrix.sh`.** The reply fork added `tomokv-reply-buffer-transfer` (bool); knob_matrix's drift-guard flagged it LIVE-BUT-UNTESTED → NO-GO. Add a `try <knob> no` + `try <knob> yes` cell (bool configs take yes/no, NOT 0/1). Same for any numeric knob (`try <knob> 0` + a nonzero). See also [[thredis-preflight-contract]].

**4. Per-command throughput: single-connection p32 is drift-sensitive.** A custom RESP driver at pipeline-32 on ONE connection runs ~500k ops/s (15x below memtier's multi-conn 8.1M) and its run-to-run variance is ±10%; a BEFORE-then-AFTER pass ordering turns that into a fake ~−15% "regression" (p1 latency stays flat — that's the tell). Interleave BEFORE/AFTER per command (two idle servers, measure back-to-back) OR trust memtier multi-conn for the fast-path verdict. The audit-range fast path was FLAT (memtier: GET p32 +0.07%, SET −0.13%).
