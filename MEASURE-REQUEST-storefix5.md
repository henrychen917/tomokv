# Store round-5 fixes

## storefix5

Worktree `/home/user/Projects/cx-storefix5`, branch `cx-storefix5`, PRE
`ea48a6b2721a1d9e5964ab24a32e8b54df611bd5`. No push. All lane builds and
correctness children are restricted to CPUs 16–23 and ports 21600–21699;
every server boot has `LC_ALL=C`. No throughput measurement is authorized here.

This report is being completed alongside the three item commits. The idle-clock
accounting item will be the last production commit and independently removable.

### RANDOMKEY

PRE's directed witness reaps all 400 expired keys in one call even when every
shard has a live survivor. The production scatter now chooses one shard using
published namespace key counts, samples uniform physical slots there, and keeps
only its selected key. A missed bounded probe uses the existing resumable SCAN
cursor and a one-key reservoir; an empty shard retries the remaining shards
before nil. Published counts are hints, never evidence of emptiness. Expiry,
CLIENT PAUSE, snapshot retention and the MVCC read cut remain in force.

EXEC retains its existing all-shard participant mask and bounded scan turns,
with one reservoir candidate per shard. Changing that transaction routing would
exceed this fix. Sparse namespaces and pending MVCC images still require the
fallback walk; no constant-time claim applies to those cases. The ordinary
populated-table path has constant expected probes and O(shards) routing work.

The old unreachable handler is removed. `tests/store_regression.cc` now invokes
the same resumable store sampler as the executed scatter path for frozen elapsed
objects, undecided candidates and parked predecessors. The Makefile's standalone
store regression link now includes `flush.cc`, matching the gate's existing link.

### Evidence so far

* `docs/storefix5/pre-randomkey-2s.log`: PRE fails the all-shard reaping witness.
* `docs/storefix5/pre-{1s,2s}.log`: PRE also fails idle-clock accounting.
* `docs/storefix5/append/pre-result.json`: the production APPEND witness detects
  its merged scratch allocation and fails on PRE.
* `docs/storefix5/randomkey-unit.log`: production sampler's snapshot/MVCC cases.
* `docs/storefix5/randomkey-exec-post-2s.json`: sampling, empty/all-expired nil,
  EXEC SET/DEL and namespace/SWAPDB checks pass after retaining EXEC participants.
* `docs/storefix5/counts/pre/counts.json`: 80 finite serverless command scopes,
  including both images, modes, atomic settings and batches 1/32.

The initial one-shard EXEC retry draft hung because transaction stages and
participants are fixed. It was rejected; that failure is preserved in
`docs/storefix5/randomkey-post-2s.log`. The live implementation retains EXEC's
existing participants instead of extending the transaction architecture.

Gate planner constraint: the existing job interface requires 8 server cores plus
2 disjoint client cores. Only eight CPUs are assigned to this lane. A question
about a partial-correctness-only shared-CPU option is pending. No planner bypass,
extra CPU allocation, full iteration, or EXPECT constant edit has been made.

DQ=0 / DF=0 so far: existing rows are strengthened and no collector is added.

### APPEND

The final raw replacement is built directly from old bytes plus suffix. TTL
storage, eviction metadata, publication failure cleanup, notifications and the
ordinary immutable replacement path are retained. `string_append.h` contains
the new cold helper. No in-place capacity growth or object layout change.

The linker allocation witness fails on PRE (one full-length scratch malloc)
and passes on POST (zero). Its memcpy spy observes 1,048,576 bytes on POST;
inlined copies are outside that spy, so PRE's external-copy total alone is not
a complete byte census. The scratch allocation is the deterministic witness.
Both-mode live results are in `docs/storefix5/append-post-{1s,2s}.json`.

After the freeze, the smallest design to investigate is capacity-bearing raw
string storage with an owner-only append eligibility check: no read-local
readers, no snapshot pre-image, no MVCC predecessor and no outstanding borrow.
All other cases still need COW. A frozen prefix or independently owned chunks
would be necessary to amortize growth while those readers remain armed. Both
are architecture decisions; neither is implemented or claimed O(1) here.
