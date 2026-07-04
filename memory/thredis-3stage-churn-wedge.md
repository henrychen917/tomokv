---
name: thredis-3stage-churn-wedge
description: 3-stage large-reply wedge (>16KB replies never sent) — FIXED; was misdiagnosed as churn
metadata: 
  node_type: memory
  type: project
  originSessionId: 192d33d7-f025-4e9c-82b2-54335e52614f
---

The 8h sweep (2026-06-28) showed every 3-stage system failing at the 16KB-value cells (only 33-37% of cells valid; 2-stage 100%). Initially hypothesized as connection-churn, but a churn repro (2000+ conn open/closes) did NOT reproduce. The real trigger: **large replies**. A 16KB-value GET reply (~16400B) exceeds the 16KB static `c->buf` and spills into the reply LIST (`c->reply`) — and `wbDrainClient`'s send was gated on `listLength(c->reply)==0`, so the WB **never sent list-based replies**. A single 16KB GET wedged the whole server (memtier hangs waiting for the reply; `ping`/small replies still worked, which made it look intermittent).

**FIX (committed c6d293db6 on 3stage-ifid-ex-wb; cherry-picked bd3dda08a on -pool):** when `listLength(c->reply)>0 || c->buf_encoded`, the WB sends via `_writevToClient` (buf+list+encoded writev) instead of the buf-only io_uring/epoll fast path. WB-safe: it's the sole sender for strict clients, `_writevToClient` does no event-loop ops, and a partial write leaves the remainder for the next WB scan; small non-encoded replies keep the fast batched buf-send. `_writevToClient` un-static'd + declared in server.h. The closing-drained return also now requires `listLength(c->reply)==0`.

**Validated:** 16KB sustained GET 0 → ~350k ops/s (was WEDGED iter 1); no wedge 64B→64KB; large values round-trip correct (16384/16385/65536); no crash. **Repro for regression:** sustained `memtier -d16384 --ratio 1:9` against a USE_URING 3-stage server → must give steady ops, not 0.

TODO: propagate the same fix to 3stage-wb-sendonly (different WB code). With this fixed, re-run sweep8h.sh clean (it was the only thing blocking complete 3-stage data). See [[thredis-tiered-pool-validated]], [[thredis-strict-needs-liburing]].
