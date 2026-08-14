---
name: thredis-pernode-control-plane
description: "Per-node semi-main (#67/#27): what may go per-node (flip DECISION only) vs what MUST stay on the real main (migration/resize/reclaim coordinators — moving them = UAF/lost-write P0). Opus hazard review 2026-08-12."
metadata:
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

Opus adversarial pre-implementation review (register: `$J/PERNODE_HAZARD_REGISTER.md`) of moving the
single-global-main control plane to per-node "semi-main" drivers. The owner's regression fear was
CORRECT and the review located the exact surface.

# Single-node is safe BY CONSTRUCTION
On topo_nodes==1 a node's semi-main IS the real main (its io-slot-0 == iotid==0), so nnodes==1 = one
driver = no change. Bit-identical reduces to ONE tripwire: assert every control-plane drive entry is
reached under iotid==0 when nnodes==1. Today NO non-main IO slot runs any control plane
(beforeSleepIO does none; every coordinator/flip/reclaim/resize drive is iotid==0-gated).

# OWNER INTENT CLARIFIED 2026-08-12: PARTITION per-node, don't leave on main
The real main must NOT be a per-node bottleneck. Delegate ALL in-node control-plane work to per-node
in-node mains; ONLY genuinely-global state stays on real main. The register's "must stay on main"
verdicts were about NAIVELY adding a 2nd driver to a SHARED global singleton (2 drivers/1 state =
race) — the CORRECT way to hit the owner's goal is to PARTITION the state per-node (each node its own
copy) so there is no sharing and no race. Decision rule per duty: node-local state -> per-node main +
per-node state; global state -> real main.
Per-item verdict under this rule (supersedes the "stay on main" reading below for the partitionable
ones):
- KEY-LB / reshardAutoTune: NODE-LOCAL -> per-node (scan only that node's workers; per-node arrays).
  Owner's explicitly-named target.
- FLAT-RESIZE: tables ALREADY per-node (node_dbs[node][db]); only flat_rz_* is a global singleton ->
  give each node its own flat_rz_* + node-scoped worker-park -> per-node.
- RECLAIM: per-worker already -> make the drain drive per-node (each node's main drains its tables);
  single-consumer-per-table preserved (that node's main is sole consumer).
- FLIP: already node-local -> per-node (promote the 4 statics).
- MIGRATION CUTOVER: SPLIT — decision+ARM node-local (per-node main, already mig_arm_lock-serialized);
  the DRAIN FENCE genuinely spans all IO producers -> its cross-IO drive stays on real main / single
  elected driver.
- Process/memory stats, cronloops: GENUINELY GLOBAL -> real main.
cxnuma re-briefed to this (BRIEF3), one duty per commit. Validate: single-node iotid==0 tripwire +
simnode-2 per-node-engagement witnesses per duty.

# (original narrow reading, kept for the reasoning) MAY go per-node (safe): the flip DECISION
fctl[] and fc_prev_*[] are ALREADY [TM_MAXNODE]-indexed; the flip claim is a correct global CAS. The
ONLY blocker to safe per-node flip is FOUR function-local statics not node-indexed — promote to
[TM_MAXNODE]: prev_wall, last_log, last_pool_warn, pool_warn_n (server.c ~25576, 25617-18). The
per-node semi-main carries ONLY: that node's flip sampling + decision + its io/ex actuation, on a
PER-NODE tick counter (NOT global cronloops; NOT loop-rate from beforeSleepIO — that fires 250x+).

# MUST stay on the real main (moving them = P0):
1. CUTOVER/MIGRATION coordinator (co_state, server.migration.*, the FLIP write to ex_bucket_table
   ~16053): process-global singleton, single-writer ONLY by the iotid==0 gate. Second driver =
   lost-write/UAF (the code's own comment ~15395-406 forbids it). iotid==0 GENUINELY breaks for
   node k>0 (leave gate: node-k has no coordinator = wedge; widen: N drivers = P0). Coordinator is
   inherently global (nprod spans all producers). Per-node semi-mains may ARM migrations (already
   serialize on mig_arm_lock + migration_active) but must NOT DRIVE the cutover machine.
2. FLAT-RESIZE coordinator (flat_rz_*): only the state EDGES are CAS-protected; the COPYING body
   (~9431-47) races flat_rz_cursor + double flatTableRetire = UAF (pre-documented prior P0).
3. RECLAIM (flatReclaimAll batch-drain ~9197-233): single-consumer of each table's batches MPSC;
   second consumer double-frees.
4. Memory/process stats: per-PROCESS, not node-partitionable.

Other flagged: tmFlipTick double-drive = POOL BROKEN (io_threads_live double-inc); reshardAutoTune's
mig_* arrays + mean/var are STRUCTURALLY global (whole-worker-set), not just unsynchronized — cannot
naively per-node. Validation: 11-point simnode-2 gate (each hazard -> a must-observe counter) + the
single-node iotid==0 tripwire. cxnuma brief was CORRECTED to this narrow scope mid-build (the
original said "move reclaim/reshard-coordinate per-node" = the P0); commit 9dc13bb30 (per-node AUTO
pools) kept. See [[thredis-flip-controller-frozen]], [[thredis-resize-single-driver-wedge]],
[[thredis-flip-pool-broken-p0]].
