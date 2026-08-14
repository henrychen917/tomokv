---
name: thredis-reorder-ryow-fix
description: "tomokv-reorder>0 broke read-your-own-writes 100% (fence identity + cross-shard bypass); fixed, drain made surgical, perf-neutral"
metadata:
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

The Shinjuku reorder (`tomokv-reorder` 1/2/3, server.c ~3099 admission front → `tomoReorderDrain`
~2873) broke **read-your-own-writes 100%** at EVERY level for a pipelined `SET k...; MGET ...k...`
(and single-key `SET k; GET k`): the MGET saw the pre-SET value. Two independent root causes:

1. **Fence keyed on `fk->parent`** (server.c 2851/2928). A real client's own single-key commands
   have `fk->parent==NULL`; its cross-shard sub-fakes have `fk->parent = the real client`. So a
   client's SET (dep=key-only) and its own MGET sub-read (dep=key^client) never collided ⇒ not fenced
   ⇒ reorder emitted the read before the write. Fix: fence by CONNECTION identity `parent ? parent :
   self` — a real command and its own sub-fakes share id; distinct real clients still differ (stay
   correctly reorderable). Fixes single-key.
2. **Cross-shard scatter bypasses the scratch.** `csDispatch` (server.c ~7285) enqueues sub-ops
   DIRECTLY into owner queues, but a staged single-key write sat in the reorder scratch (NOT yet in
   the queue), so the sub-read enqueued AHEAD of it — breaking the "same key ⇒ same owner queue ⇒
   FIFO" invariant scatter-gather relies on. Fix: flush the scratch before the cross-shard dispatch.

**The drain is an ENQUEUE, not a wait** — `exDispatchDirect` hands staged commands to worker queues
and returns; workers never stop, so it does NOT serialize execution. It only shrinks the reorder
STAGING window. A blanket drain-before-every-cross-shard-command was still over-broad (one conn's
read flushed EVERY co-located conn's staging), so it was made **surgical**: `tomoReorderDrainConn(conn)`
emits ONLY conn's staged entries (arrival order) and compacts survivors — RYOW/write-order is
per-connection, so that's all correctness needs; other conns keep their SJF batching.

Commits on 2s-numa-stable-dev-work: b96ac3bce (both root-cause fixes) + 7518522cd (surgical).
VALIDATED: RYOW 0 at reorder 1/2/3 (multi-key, single-key, churn). PERF: inert at reorder=0 and for
all cross-shard commands (server.c 3099-3101 EXCLUDES `csparent` AND `TOMO_R_CROSS` from staging, so
pure MGET8/MSET8 never stage ⇒ the drain is a no-op branch — a first-run "-9.5% MSET8" was
flip-convergence NOISE on that provably-inert path, +4.1% on re-measure; [[thredis-sanity-gate-benching]]
caught it). Single-key GET/SET (the only path the fence code runs) neutral (-0.7%/+0.1%, 4-rep median).
Mixed SET+MGET8 saturated: broken 2.94M / full-drain 2.85M / surgical 2.87M — all within ~3% noise,
so the drain does not kill batching. Cherry-picked to the atomicity branches. See
[[thredis-mset-atomicity-bakeoff]], [[thredis-reorder-overhead-and-wall]], [[thredis-3stage-hotkey-wedge]].
