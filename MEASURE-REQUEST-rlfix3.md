## rlfix3

Base: `05a5e01a9d8f1236e11cdbe4f2f7d490eb40edba`. Worktree/branch:
`/home/user/Projects/cx-rlfix3`, `cx-rlfix3`. No push. Builds and correctness
children are confined to CPUs 96–111 and ports 38800–38899.

### RL4.11: explicit lifetime constraint

Used the task's permitted documentation/capability alternative. Lane replies
still copy. `CONFIG GET zc-min-read-local` now returns `0` (read-only, no CLI or
config-file knob); `CONFIG GET zc-min*` reports both it and the live owner
threshold. Owner GETs and owner fallbacks retain their exact >= threshold rule.

Why a direct lane borrow is unsafe: the reader's immutable pointer is protected
until its next rotation publishes a QSBR tick (`ThreadCtx` rotation/park
publication). Replacement retires the old object in `ReadLocalRetireRing`;
`drain_below` releases it once all ticks pass its stamp. Neither the ring nor
tick publication consults pending sends. `tests/rlfix3_lifetime.cc` exercises
the real ring: the next rotation permits reclamation while an `Op::zc_ptr`
descriptor is still live. The separate owner borrow vector/index retains owner
GET values until writeback sends a release back to that owner. Foreign writes
to that registry would violate single-owner mutation and race vector growth,
index updates, retirement and release. A send-lifetime pin or registration
handshake would be a new lifetime protocol, outside the fixed lane design.

PRE reproduction: `docs/rlfix3/pre-zc-ledger.tsv` and
`docs/rlfix3/pre-zc-reproduction.log`. All eight new gate rows run every threshold
and venue assertion, then fail on the missing capability. Both modes, both
engines, read-local 0/1; value sizes 1024/16384/262144; thresholds 0/N/N+1.
The existing zero-copy job passes all release/ASAN legs on PRE. No timing or
throughput estimates are taken by these witnesses.

RL4.5 and RL4.6 (read in full with the scope report) do not change: eviction
still makes writes conservative for RYOW, and split read-local still enables
coded replies. A split rl=0/1 comparison includes that coded-reply effect.

### Pending proof and merit request

RL4.15 implementation and final proof inventory are in progress. Performance
measurements are NOT RUN by this lane: the task reserves performance benchmarks
and measurement generators for the maintainer. This includes INFO server
latency (16/256 shards), large GET instructions and copied bytes, and the
generic 14-cell merit comparison. Final binary hashes, PAD-A construction,
commands, results and remaining NOT RUN items will be recorded here.

The RL4.11 job adds eight rows collected before the quick-tier exit:
DQ=+8, DF=+8 so far. `EXPECT_QUICK` and `EXPECT_FULL` remain untouched.
