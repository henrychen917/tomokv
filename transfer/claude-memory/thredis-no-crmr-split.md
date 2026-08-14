---
name: thredis-no-crmr-split
description: "OWNER RULE — do NOT adopt uTPS's cache-resident/memory-resident layer split; IO and EX stay the only stage boundary. Take the mechanisms, not the architecture."
metadata: 
  node_type: memory
  type: feedback
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

**Owner, 2026-08-09, explicit:** "I explicitly don't want CR/MR split like they do. I want ex and io
to be fully separate like we have always done."

μTPS (SOSP'25, Chen et al., *Rearchitecting the Thread Model of In-Memory Key-Value Stores*) splits a
KVS into a **cache-resident** layer (hottest items + network buffers, dedicated worker threads and
dedicated LLC ways) and a **memory-resident** layer (full index/data, batching + prefetch +
coroutines), joined by a CR-MR queue. **We are not doing that.**

**Why:** THredis's IO/EX split is the stage boundary. Adding a hot/cold layer boundary on top means a
second queue hop, a second thread pool to size, and requests that cross layers on a miss — and the
whole point of this architecture is that a request lands on its owner and runs to completion there.

**How to apply:** take μTPS's MECHANISMS where they fit the split we already have; reject anything
that changes the thread architecture.

| μTPS idea | verdict here |
|---|---|
| CR/MR layer split + CR-MR queue | **REJECT** — owner rule |
| dedicated hot-item thread pool | **REJECT** — same reason |
| separate network buffers from index/data | **already have it** — that IS the IO/EX split, and it is the source of their headline 1.22-1.54x |
| dedicated LLC ways per stage (`cat_l3`) | **KEEP AS EXPERIMENT** — apply to the EXISTING IO vs EX roles, no restructuring |
| hot-set by count-min sketch + epoch swap, NOT LRU | mechanism worth borrowing IF a hot set is ever built; the paper explicitly rejects LRU as too costly to bookkeep |
| AMAC | **REJECT** — owner said "no amac", and server.h already explains why: constant-depth probe chains, so AMAC's refill never fires |

**The gains are unlikely to be there anyway** — see [[thredis-worker-overhead-bound]] and
[[thredis-prefetch-truth]]: ~2.0M ops/s per worker in every config, 21x dataset costs 3.5%, and
prefetch is a WASH with its gate 97.8% open. μTPS's cache-residency premise is that misses dominate.
Also the paper's own scope note: gains are "modest" for hash indexes and uniform workloads, and we
are both.

**Hardware note (verified 2026-08-09):** the 7700X DOES expose AMD RDT — `cat_l3`, `cqm_occup_llc`,
`cqm_mbm_total/local`. An earlier claim of mine that AMD had no CAT equivalent was WRONG. `resctrl`
is kernel-supported but NOT mounted; mounting needs root, which is the only blocker to running the
way-partitioning experiment. See [[user-autonomy-no-permission-asks]] — sudo is the one thing to ask
for.
