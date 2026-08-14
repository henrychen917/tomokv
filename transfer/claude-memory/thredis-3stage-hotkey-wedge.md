---
name: thredis-dropped-dispatch-bug
description: Hot dispatch sites ignore exQueuePush's -1 (queue-full) -> SILENT dropped fake -> lost reply -> wedged client under single-key saturation. Real bug in BOTH editions; fixed on 3s dev branch.
metadata:
  type: project
---

**REAL correctness bug, root-caused 2026-07-09** (started as the mis-labeled "3-stage hot-key wedge").
NOT a server wedge, NOT memtier, NOT the reshard — it's a **silently dropped worker dispatch = lost reply**.

THE GAP: the two hot dispatch sites in processCommand (express-lane GET/SET + whitelist worker branch)
call `exQueuePush(...)` and IGNORE its return, while still doing `dispatchid++`. `exQueuePush` returns
**-1 when the owning worker's per-(ifid,ex) SPSC queue is FULL** (drops the fake). The cross-shard path
`csPushSpin` handles full correctly by spinning; the hot paths did not. Dropped fake -> consumes a
pipeline-ring slot the worker never runs -> reply-ready bit never set -> flushid can't advance -> ring
wedges full (dispatchid-flushid==depth) -> client stalled FOREVER, tail replies never produced. Server
stays fully alive (only the saturated conns wedge). LOST not deferred (drop counter hit 498 & froze;
stuck clients: worker bit never set, nothing queued to send).

TRIGGER: single hot key + deep pipeline (P32) funnels all conns to ONE worker whose queue
(ex_queue_size 2048) < clients_per_ifid(~66) x ring_depth(32). 3-STAGE triggers it (decoupled IO-dispatch/
WB-retire timing lets the queue back up); 2-STAGE has the IDENTICAL code (garnet-ideas server.c:5215/5240
ignore the return; 3s at 5340/5365) but its faster reply-drain kept the queue from overflowing at
io4ex4/2048 in test -> LATENT there (could trigger at smaller queue / io2 / more clients). Affects
canonical STABLE (2s) + 3-stage.

FIX (validated on 3-stage): `exDispatchPush` helper — on the full case, publish staged tail (worker
drains), bounded spin (worker pop rate, never waits on IO thread), retry, publish; mirrors csPushSpin.
+25/-2 server.c. Repro rc=137->rc=0 ~7M, drops 498->0, ASAN-clean, no regression. Branch 3s-wbtail-fix,
commit 8a5b104515, canonical untouched. 2-STAGE fix (same pattern) IN PROGRESS. MERGED to canonical 2026-07-09 (user-approved): stable=main=11358e75b, 3-stage=0aae35cc7. Repro: hk3s_noreshard.sh; drop-repro needs small --tomokv-ex-queue-depth for 2s.
See [[thredis-3stage-churn-wedge]] (same class, one stage downstream).
