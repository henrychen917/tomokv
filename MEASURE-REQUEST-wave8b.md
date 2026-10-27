# Wave 8b latency off-path repair

## wave8b

Base `83e0b809d`, branch `cx-wave8b`; no push. CPUs 64–79 only, builds -j16,
correctness listeners 20000–20099. Throughput measurements remain owner-owned.

### Before any production edit

All 144 serverless EXEC traces completed: headline `3700b51d7`, execindex
`7ae703778`, and PRE `83e0b809d`; both physical namespaces, both modes,
atomic 0/1, 1/2/4 INCR children, single-shard and cross-shard key placement.
Each trace checks exact replies and bounded completion. One INCR necessarily
has only one shard; the one-child cross case is intentionally the same geometry.

The scope starts at MULTI handling, queues every INCR, executes production
transaction fragments, retires EXEC on IO, reclaims owner records and destroys
the deferred state. It excludes protocol parsing, socket IO, idle loop passes,
fixture glue and library callees. It is a command-scope count, not a rate or
whole-process count. Traces use the production object order and fix clock values.

`docs/wave8b/baseline.json` contains all comparisons; individual function counts,
excluded callees, fixture binary digests and GDB completion receipts are in
`docs/wave8b/instructions/`. Reference source/objects are frozen under build/wave8b.

| Namespace | Shape | Children | Headline | Execindex | PRE | PRE − execindex |
|---|---|---:|---:|---:|---:|---:|
| normal | EXEC-single | 1 | 13598 | 13915 | 15749 | 1834 |
| normal | EXEC-single | 2 | 20713 | 20983 | 24597 | 3614 |
| normal | EXEC-single | 4 | 35988 | 36164 | 43338 | 7174 |
| normal | EXEC-cross | 1 | 13598 | 13915 | 15749 | 1834 |
| normal | EXEC-cross | 2 | 22984 | 23335 | 27145 | 3810 |
| normal | EXEC-cross | 4 | 41604 | 42020 | 49782 | 7762 |
| db0 | EXEC-single | 1 | 12396 | 12686 | 14520 | 1834 |
| db0 | EXEC-single | 2 | 19046 | 19279 | 22893 | 3614 |
| db0 | EXEC-single | 4 | 33277 | 33402 | 40576 | 7174 |
| db0 | EXEC-cross | 1 | 12396 | 12686 | 14520 | 1834 |
| db0 | EXEC-cross | 2 | 21267 | 21577 | 25389 | 3812 |
| db0 | EXEC-cross | 4 | 38833 | 39178 | 46946 | 7768 |

These are instruction counts only. The initial one-child normal trace enters
793 instructions in latency_tracking_retire and 915 in latency_tracking_forget,
despite tracking being off and all stores empty. The scope constructors,
destructors and explicit finish add 92 more instructions. Final attribution,
correctness, identities, artifacts and the owner's merit request follow below.
