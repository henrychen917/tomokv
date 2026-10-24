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

### RL4.15: selective collection and maintained counts

PRE reproduction uses the actual INFO handler linked with PRE production
objects. Readable-page controls return successfully; making the filter pages
unreadable makes `INFO server` fault in both modes at 16 and 256 shards
(`docs/rlfix3/pre-info-reproduction.json`). This proves the walk, without
claiming a latency result. INFO latency remains NEEDS-RUN with the maintainer.

POST resolves STATS/MEMORY/KEYSPACE/COMMANDSTATS selection before gathering.
Unrequested statistics, command-call totals and RESETSTAT baselines are not
collected. Existing output formatting, order and selection rules are retained,
including default/all/everything, case folding and multiple-section unions.

`ForeignReadSafety` maintains occupancy/wildcard gauges on cell transitions.
The two atomic words fit existing tail padding: sizeof remains 49216, and all
locked enclosing layouts are unchanged. The disabled lane allocates nothing.
Counts are exact after owner transitions complete, with the usual independent
INFO sampling of in-progress updates; no periodic cache or reader retries.
Saturation drain and permanent poison explicitly publish their final counts.
`tests/rlfix3_info_unit.cc` tests collisions, sticky wildcard/nested poison,
saturation/rebuild, permanent poison, protected cell pages and protected store
state for metadata-only requests. External identity/time/allocator facts are
fixed in this serverless executable only for exact reply comparisons.

The first POST directed gate selection passes 28/28 rows, including both new
jobs, B+, read-local admission/fence/miss/delete, filter and configuration jobs
(`docs/rlfix3/post-directed-initial-ledger.tsv`). Final frozen-artifact proof is
still in progress.

### Pending proof and merit request

The final proof inventory is in progress. Performance
measurements are NOT RUN by this lane: the task reserves performance benchmarks
and measurement generators for the maintainer. This includes INFO server
latency (16/256 shards), large GET instructions and copied bytes, and the
generic 14-cell merit comparison. Final binary hashes, PAD-A construction,
commands, results and remaining NOT RUN items will be recorded here.

Each item adds eight rows (mode × engine × read-local), all collected before
the quick-tier exit: **DQ=+16, DF=+16**, required **784 quick / 801 full** from
768/785. `EXPECT_QUICK` and `EXPECT_FULL` remain untouched. The explicit label
fixture includes the 16 additions; the source-label check must still report the
maintainer-owned EXPECT mismatch until those constants are updated.
