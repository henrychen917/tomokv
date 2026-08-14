---
name: thredis-right-sized-tests
description: "USER RULE — tests should be just long enough to prove the change works and didn't break neighbours; not exhaustive. Balance against the vacuity trap: short is fine, uninformative is not."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Owner, 2026-07-28: *"tests don't have to be super long just enough to correctly test what has
changed and general behavior make sure it doesn't break other stuff accidentally."*

**Why:** validation had ballooned into hours-long suites that monopolised the single box while ten
workstreams queued behind it. The binding constraint all night was box time, not analysis — several
branches were fully written and adversarially reviewed but never executed once. A 20-minute suite
that answers the question beats a 3-hour one that never gets to run.

**How to apply — a test needs exactly three things:**
1. **Discriminates on the change.** It must FAIL on the pre-fix binary and PASS after. Run it
   against the old build and *see* it fail; a test never observed failing proves nothing.
2. **Covers the neighbourhood.** `correctness_suite` 15/0 (or the relevant subset) to catch
   accidental breakage. Not the full matrix.
3. **Stops there.** No exhaustive sweeps, no every-knob-combination, no 10-minute cells where 20
   seconds resolves it.

**The tension to respect — short is fine, UNINFORMATIVE is not.** This does not license the
vacuity failures in [[thredis-vacuous-validation-trap]]:
- A **flaky** defect still needs repetition. The qb_pos assert ran at ~20-30% per run, so a single
  green run was luck, and a ship gate once reported "FAILs=0" on exactly that sampling noise. Rate
  matters: N=1 is a measurement only for deterministic defects.
- A **gated** feature still needs proof the gate OPENED. Short does not mean skipping the counter
  that shows the machinery ran.
- A **conformance** test must still report SKIP, not PASS, when the condition it needed never
  materialised (no skew formed, no outlier appeared).
- **Perf** claims still need ABBA interleaving and >=3 reps — but 20s cells, not 2min.

So: shrink the DURATION and the BREADTH, never the DISCRIMINATION. If a cheaper test cannot tell
the two arms apart, it is not a cheaper test, it is no test.

## Two tiers: short per change, LONG after a batch

Owner, same conversation: *"after enough changes then do the longer test."*

**Tier 1 — per change (short).** The three requirements above. Gates that one merge.

**Tier 2 — after a batch accumulates (long).** Full preflight, extended stress/churn, ASAN, the
competitive sweep, longer soak. Gates the batch.

**Why tier 2 is not optional, and why tier 1 cannot replace it:** per-change tests validate changes
IN ISOLATION. They cannot see INTERACTION. Nine individually-green merges can combine into a broken
tree, and this fork is full of the ingredients — features gated on `shared_node_dbs`
(FALSE at `thread-ex 1`, so DICT-backed there and FLATSTORE at ex>=2, i.e. two different engines),
per-thread state that several changes touch at once, and a flip controller whose inputs half the
subsystems publish into. The long run is also where slow/rare classes surface at all: memory growth
(active expiry never ran and NO functional test could see it — lazy expiry kept every observable
read correct), reclamation stalls, flaky asserts whose rate only shows over many runs.

**PUSH ON EVERY GREEN.** Owner, 2026-07-29: *"after every passed quick test push with comments to
dev branch."* So the unit of work is: change -> `tools/preflight/postmerge.sh` -> if green, COMMIT
AND PUSH to `2s-numa-stable-dev` immediately, with a message saying what the change fixes and what
the numbers were. Do not accumulate green work locally.

Why this is the right default here rather than batching pushes: this session lost real work to the
opposite habit. Three merges sat locally "pending validation" and were then pushed anyway without a
green; a whole merge campaign died mid-queue on a spend limit with 7 steps unpushed; and two agents
sharing one index had a `git commit --amend` swallow 15 staged files. Unpushed green work is the
fragile state. The commit message is where the evidence lives — record the acceptance result and the
four postmerge cells, because a bare "fix X" commit forces the next person to re-run what you
already proved.

Practical shape: push each green change immediately, then one long validation after a BATCH before
any comparison benchmark. Under [[thredis-preflight-contract]] the GO stamp is exactly this
tier-2 gate. If tier 2 fails after a batch, the per-change results are still good evidence for
WHICH change to bisect toward — that is the payoff for having made each one discriminating.

Related: [[thredis-quickcheck-protocol]] (the 8-cell standing check is itself an instance of this),
[[thredis-three-regime-testing]], [[thredis-sanity-gate-benching]], [[thredis-preflight-contract]].
