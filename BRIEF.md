REBASE-REPLAY: branch 2s-atomic-retdiet2 tip e32918583 "atomic: collapse version
retirement waits" (+3.8% measured on its own base) must be replayed onto THIS
tree (dev + ownread replay + budgeted reclaim). A direct merge was attempted
2026-08-09 and ABORTED as architecturally unmergeable. The recorded conflict:
retdiet2 RESTRUCTURES retirement — TOMO_RETIRE_PRUNE_UNLINKED state,
committed_next reverse links, tomoEnqueuePhysicalRetire batching, bare
decrRefCount — while THIS tree uses the LIFECYCLE-PIN protocol
(tomoAtomicLifecycleAcquire/Release, tomoVersionPruneFinish keeping vmeta valid
through callbacks). A half-migrated state machine here is a UAF factory.
YOUR JOB: study `git log -p 83e0600c7..e32918583` (the branch exists in this
repo; the relevant commits are reachable) and REIMPLEMENT its retirement-cost
reductions ON TOP of this tree's protocol, site by site:
 - EITHER map each retdiet2 site onto the lifecycle-pin protocol (keep pins,
   adopt the wait-collapse/batching), OR replace the protocol wholesale —
   consciously, completely, with the replacement's safety argument written in
   comments at the replaced sites. NO half-migration.
 - This tree ALSO just gained: (a) generation-counted read pins may land in a
   sibling branch (do not touch flatExternEnter/Exit or flatBatchReady), and
   (b) flatWorkerReclaim/flatReclaimAll are now BUDGETED (flatReclaimBudget,
   2*closed+4) — your batching must compose with that budget, not bypass it.
 - The known cost being attacked (measured): version retirement is ~11.5x the
   per-pass tax of commit/install on the atomic write path, and
   tomoVersionPruneAfterGrace's full-bag triple walk dominates worker time
   whenever bags are deep. Wait-collapse + retire batching are the levers.
CONSTRAINTS: preserve EXACT current semantics of visibility (committed frontier
rule: a callback retires only seq < its anchor frontier; canceled nodes only
after their own grace), RYOW own-origin resolution fields
(install_order/origin_client_id IMMUTABLE until physical retire), and the
single-writer owner affinity (stamps/cancels/prunes on the key's owner worker).
Every new deferral needs a liveness argument (who eventually runs it) written
at the site. Commit in reviewable pieces (state-machine prep, then site
migrations, then batching) — multiple commits welcome.
