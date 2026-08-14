---
name: thredis-flat-path-deleted
description: Flat-native / work-stealing M-read path DELETED 2026-07-27 — proven to break same-client pipeline ordering 39% of the time; why the inflight_writes gate could never fix it
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**DELETED at `867d79648` on `2s-numa-wave-dev`. Do not reintroduce a non-owner read path without
solving the read->write direction first.**

The flat-native route sent a whole MGET to ONE executor which read keys it does NOT own, lock-free
off the shared flat table. **Measured: 1547/4000 (39%) ordering violations** — an MGET issued
BEFORE a SET in the same client pipeline observed the SET's new value. The probe reported
`taken=4000 gated=0`, proving the flat route genuinely ran with the gate open (not another vacuous
measurement — see [[thredis-vacuous-validation-trap]]).

**Why the `inflight_writes` gate could never fix it.** There are two directions and it only closed
one:
- **write -> read** (`SET k; MGET k`): closed — writes in flight force the MGET back to scatter.
- **read -> write** (`MGET k; SET k`): WIDE OPEN. The flat MGET runs on executor A while the later
  SET runs on k's true owner B, and **nothing orders A against B.**

36k stolen reads never reproduced it because they only ever probed the direction the gate already
covered. Scatter is correct by construction: a key's sub and any later write to that key both land
on that key's owner and queue FIFO.

**A correct design does exist** (not built): keep the forward gate AND add a reverse barrier — a
write from a client with a flat read outstanding stalls via `CLIENT_PIPELINE_STALLED` (the same
"acquire with an empty ring" idiom the script fence uses) until the read retires. Reads never block
reads, so pipelined MGETs still run parallel. Optional refinement: scope the barrier to the buckets
the outstanding read touched so writes to disjoint keys never stall.

**But it is probably not worth it** — see [[thredis-unified-path-closed]]: the +68% was scatter/
gather fixed-overhead removal, and at 9:1 the per-batch firing probability collapses with pipe
depth (0.9^N: p8 43%, p16 18%, p32 3.4%).

Removed with it: `tomokv-mcmd-flat`, `tomoMgetFlatNative`, `tomoMgetLockBorrow`, the whole
`inflight_writes`/`CLIENT_TOMO_WRITE` gate, the `tomo_mread_flat_taken/gated` counters, and the
`tomoStrGrowLock` grower co-op brackets (unreachable — gated on `!mcmd_flat`). CS_MGET/CS_EXISTS
borrow subs reverted to LOCKED reads. KEPT: scatter, `mcmd_lock` + the S2 single-key owner lock,
FLATSTORE/QSBR/epoch, `TOMO_MWAVE`/`TOMO_MSUBWAVE`.

**Correction to an earlier claim of mine:** `tomoFlatMWaveProbe` was NOT used by the scatter path —
CS_MSET has its own inline wave, and the probe's only callers were the two deleted flat routes.
