---
name: thredis-verify-before-implementing
description: "USER RULE — check the CODE before implementing any 'pending' task; the task list and memory are both stale. Four items were rediscovered as already-done in one session, at real token cost."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Owner, 2026-07-29, after repeated rediscovery: *"make sure those aren't done, I don't want to keep
wasting tokens on repeated works it's starting to frustrate me"* and *"make sure you don't redo the
work already done last session"*.

**In ONE session, four "pending" items were already done:**

| item | claimed | actual |
|---|---|---|
| #53 pooling/resizing replacement | pending | already deleted — zero `operand_pool`/`tiered` refs in `src/` |
| #33 bidirectional flip | pending | 22 `tomoGrowFront`/`tomoGrowBack` sites, both directions live |
| #49 cross-key ordering doc | pending | documented in `docs/BUGS.md` + `README-NUMA.md` |
| #50 csGroup SSO | "CONFIRMED not done" | **already done** at `968565c72` — my grep looked for `SSO`/`inline_buf` naming and missed the implementation |

Plus two mis-diagnoses of the same shape: the qb_pos crash was recorded OPEN in memory but fixed 3
days earlier (`fa9aca003`); the hot-key veto's parent commit was already an ancestor of the branch
tip. And `w_live + io == 7` was read as a lost thread **twice**, when `docs/STABLE_PLAN.md` §3f had
already recorded it as a known off-by-one (`io=` is `io_live_node`, which excludes iotid 0).

**THE RULE: grep the code before starting. Not the task list, not memory, not a prior report.**

A task marked pending is a *claim about the past*, and this tree moves faster than its bookkeeping —
multiple agents and sessions commit to one branch. Same for memory: a memory recording a bug as OPEN
is a snapshot of when it was written, not a live status.

**How to check properly — the #50 miss is the lesson.** Grepping for the FEATURE NAME (`SSO`,
`inline_buf`) found nothing and I concluded "not done". The implementation existed under different
naming. So:
- search for the BEHAVIOUR and its call sites, not the label you would have given it;
- check `git log --oneline --all --grep=` and `git log -S<symbol>` for the concept;
- read the struct/function the change would have modified and see whether it is already modified;
- if a doc or plan file claims it is done, verify that claim rather than trusting or dismissing it.

**And say so rather than manufacturing a diff.** Every delegated task brief should end with: *if it
turns out already done, or unreachable, SAY SO and change nothing.* An agent that produces a
plausible diff for a solved problem costs twice — the tokens, and the review time to discover it was
redundant.

Related: [[thredis-right-sized-tests]] (short but discriminating), [[thredis-sanity-gate-benching]],
[[thredis-vacuous-validation-trap]], [[thredis-ab-harness-traps]].
