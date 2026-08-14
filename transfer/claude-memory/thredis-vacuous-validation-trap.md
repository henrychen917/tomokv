---
name: thredis-vacuous-validation-trap
description: "The \"0 stale reads\" trap — a gated feature's negative result proves nothing unless you also prove the gate OPENED; plus the preflight suites that certified binaries they never ran"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**2026-07-26, found by adversarial review (49 agents), not by me.** I reported "TASK#43 fixed:
0/6000 stale reads." The number was real and the conclusion was worthless.

`client.inflight_writes` was incremented on every write dispatch but decremented ONLY in
`handleWorkerReplies`' CLOSE_ASAP teardown branch — the two live-drain retire sites never
decremented. On a healthy connection the counter only grew, so the `inflight_writes == 0` gate was
permanently false after the first write and the guarded fast path was dead. **A permanently-closed
gate produces 0 stale reads trivially.** The field was also never initialized (per-field init, no
memset) — heap garbage alone pins it shut.

**The rule: for any feature behind a gate, a negative result (no bug seen) is evidence ONLY if
paired with proof the gate opened.** Ship a counter with the gate — `tomo_mread_flat_taken` /
`tomo_mread_flat_gated` now exist for exactly this. Without them, "gate closed" and "feature off"
are indistinguishable from outside. Any validation of that path must assert `taken > 0`.

**Harness note that cost a wrong test:** every separate `redis-cli <cmd>` invocation is a NEW
connection, and `inflight_writes` is per-client — so a write and a read issued as two redis-cli
calls can never expose the leak. My first `gate_test.sh` did exactly that and PASSED the defective
binary. Write+reads must share ONE connection (pipe commands to a single redis-cli on stdin).
Always verify a new test DISCRIMINATES by running it against a binary with the defect
reintroduced — that step is what caught my bad test.

**The preflight was certifying builds it never ran** (same review): 5 of 9 suites
(knob_matrix, numa2_validate, stress_reclaim, reclaim_correctness, feature_sweep) booted hardcoded
binary paths and ignored the `TOMO_BIN` handed to them, while the GO stamp is keyed to the sha of
the binary passed on the command line. `run_suite` also graded a MISSING result file as 0 failures
= PASS, so a crashed suite still contributed to GO. quickbench tagged arms by
`basename(dirname(bin))`, collapsing two `<tree>/src/redis-server` arms into one pooled median
reporting +0.0% against itself, and only warned about ordering-failing arms instead of dropping
them. All fixed in `f2e6c6aee`. See [[thredis-preflight-contract]], [[thredis-sanity-gate-benching]],
[[thredis-ab-harness-traps]].

## 2026-08-03: the SAME class one level down — the test's *contract* with the server

Auditing whether the suites still name things that exist. Two contract surfaces, and only one was
guarded:

- **Knobs — GUARDED.** `knob_matrix.sh`'s `drift_guard()` derives the live surface from the server
  itself (`CONFIG GET 'tomokv-*'`, so no source path to rot) and fails in both directions: live-but-
  untested, and cell-for-missing-knob. It works: audited clean, 18 `try` + 8 exempt = 26 = live, and
  tree-wide every `--tomokv-*` flag in every suite names a live knob.
- **Log strings — WERE NOT GUARDED.** Every controller assertion is a fixed-string match on the
  server log, so a **renamed line reports exactly what a broken mechanism reports: zero.** This file
  had already been bitten twice; the second time the replacement string was picked *because* the
  first "could only ever report SUSPECT", i.e. it had been vacuous for an unknown number of runs.
  Fixed with a run-level **pattern ledger**: record every pattern queried and whether it EVER
  matched in ANY cell; report the never-matched set at the end. Cannot false-alarm — it only
  reports what the run itself observed — and it is the exact discriminator for a `=0` observation.

**Two verification traps found while doing it, both of which fake a "missing" string:**
1. `grep -F` on **source** cannot see a message split across adjacent C literals
   (`"...SYMMETRIC POOL — %d threads provisioned as " "1 io (main) + %d convertible..."`). It looked
   dead; at runtime the concatenated line matches fine. **Only a runtime check settles it.**
2. `strings` breaks a literal at any non-ASCII byte, so every message containing an em dash (this
   codebase logs many) reads as absent from the binary.

**Also: a `must_refuse <knob>` cell and a DELETED knob are indistinguishable** — the server refuses
an unknown parameter exactly as it refuses a below-minimum one. So a `must_refuse` cell left behind
by a retirement passes forever, and neither existing drift direction could see it (it is not in
`knob_tried`). Added a fourth check for it.

**Generalization worth keeping:** a guard that derives truth *from the running server* (CONFIG GET)
stays honest; a guard that matches *text* needs a separate proof that the text is still produced.
Same reason `server.c:NNNN` citations in the suites had rotted onto unrelated code — re-anchor
comments to quoted strings, not line numbers.


## THE DUAL FAILURE: a gate that FAILS on known-good input (2026-08-09, hit TWICE in one session)

The recorded trap is a gate that PASSES without ever opening. The dual is just as costly: a gate
that REJECTS a healthy input, so real work gets discarded or a clean tree looks broken.

1. `notifyguard.sh` reported `LOST cdbSlots is cache-line ALIGNED` on the **clean ship line**. The
   regex expected two closing parens where `__attribute__((aligned(CACHE_LINE_SIZE))) cdbSlots` has
   three. A guard that cries wolf on a clean tree trains you to ignore it.
2. The flip matrix's build gate reported `BOOT TEST FAILED -- refusing to run atomic phases` for the
   wedgefix binary. The binary was FINE. My boot command omitted
   `--tomokv-thread-io/--tomokv-thread-ex`, and this server FATALs without an explicit thread pool:
   *"FATAL: set the thread pool explicitly ... Got tomokv-thread-io=0 tomokv-thread-ex=0"*.
   Cost: phases 1b/2b (the P0 wedge validation) and phase 3 were skipped, and `MASTER_DONE` never
   fired, stalling four downstream chains.

**RULE: run every new gate against a KNOWN-GOOD input FIRST and require it to pass there before
trusting any failure it reports.** Both bugs were found that way (I ran notifyguard on the baseline;
I re-ran the boot with a control arm) — and both would have been invisible if the gate had only ever
been pointed at the thing under test.

Corollary for boot tests specifically: this fork REQUIRES an explicit thread pool. Any harness that
boots a server must pass `--tomokv-thread-io N --tomokv-thread-ex M`, or it tests nothing.
