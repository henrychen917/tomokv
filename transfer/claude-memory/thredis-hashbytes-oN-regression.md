---
name: thredis-hashbytes-on-regression
description: hashbytes (Dragonfly byte-bounded listpack) regressed HSET/HINCRBY and was DELETED; fast-path gate missed it
metadata: 
  node_type: memory
  type: project
  originSessionId: fd085c8e-0bc5-48ff-bee2-eca219253f18
---

The Dragonfly-inspired "byte-bounded listpack" queued item (commit 85f83242d, merge f72399de2)
replaced hashTypeSet's O(1) conversion check (`hashTypeLength > entries`) with
`hashTypeListpackExceedsLimits()`, which **walks every listpack entry on every write** to enforce a
per-value limit. On a 64-field hash that added a full O(n) scan on top of lpFind.

Clean magnitude (one server at a time, median of 5x2s, vs pre-audit 461359096):
**HSET -20%, HDEL -13%, HINCRBY -58%** (HINCRBY hammers one field, so the scan hit every call).

FINAL DISPOSITION: **DELETED** (revert 49241cff2 on 2s-numa-stable-dev-work). Path there:
first an O(1) fix (80638a0a3, gate the scan to the 1->2 singleton transition), then opt-in/default-off
(973a6f8e5). The owner rejected the knob -- rule is "hard-code a consistent gain or delete it, no
knob to preserve a net-negative" (see [[user-hardcode-or-delete]]). Byte-bounding only helps large
hashes while taxing every hash write, so it can't be lowered into a consistent gain -> reverted in
full (config, singleton exemption, both helper fns, byte-threshold tests). Hash encoding is back to
stock Redis. KEPT: 87d21aba0 "defer dict shrink across batched removes" -- a separate mainline HDEL
optimization bundled in the same PR, unrelated, not shown to regress; its HDEL-batch coverage stays.

**Gate gap (the durable lesson):** the fast-path gate only measures string GET/SET p32 via memtier,
so it certified this dev GO with a -58% hash-write regression in it. What caught it was the
per-command p1/p32 latency sweep (a [[thredis-sanity-gate-benching]] pass on a deliverable). The
[[thredis-quickcheck-protocol]] 8-cell check and big gate need a hash/list/zset WRITE throughput cell.

Measurement traps (all [[thredis-box-noise-truth]]): 2-server interleave UNDERSTATED it (-14%,
HINCRBY muddied to "noise"); a 3-server run OVERSTATED a fix (+149% HSET, scheduling artifact of 3
servers on 8 cores). Only one-server-at-a-time gave the true number. This box drifts +-5-7% between
adjacent boots, so for per-command THROUGHPUT deltas boot ONE server at a time and normalize by a
known-flat control (SET); reserve 2-server interleave for latency, never 3+ concurrent.
