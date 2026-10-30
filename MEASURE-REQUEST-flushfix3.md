# FLUSH collapse bound and wave 10 integration

## flushfix3

Branch `cx-flushfix3`, starting at `a396a42e5`. No push; landing awaits
the owner's D12 design approval. Work in progress; no throughput claim.

### Idle completion

The actual empty-server defect is a lost wake at the phase-two handoff.
`flush_after_decision` publishes to the cold retry inbox, which is absent from
the IO park predicate. Its conditional wake can miss an IO between its final
retry drain and publishing its parked flag. A real wake event now accompanies
every FLUSH continuation, including fused self-publication. The next IO pass
refreshes completed read cuts before redispatch. Live older cuts still protect
their versions; the cutoff-before-floor eligibility test is unchanged.
No ordinary command or idle-loop path is changed by this fix.

The gate's `flushfix3` job runs FLUSHALL/FLUSHDB SYNC/ASYNC, 1,000 idle calls
per form, in all eight mode/engine/atomic legs, in both database images.
One call above 5 ms fails immediately; passing requires all 1,000 calls.
Original flushfix2 fails every fused leg and passes every split leg. The fix
passes all 64,000 calls. Binary hashes, per-form maxima, counts and compressed
raw observations are in `docs/flushfix3/idle-proof.json` and adjacent files.
An initial negative run was stopped after one complete fused leg demonstrated
438–466 deadline misses per 1,000 calls; its observations are retained. The
completed negative rerun uses the same fail-on-first-miss rule as the fix.

The two new rows are collected before the quick-tier exit: incremental
DQ=+2, DF=+2. Final collection line numbers and combined row counts will be
recorded after the wave 10 merge. EXPECT constants have not been edited.

### Wave 10 merge

Merge `a42e527b0` has parents `b3e959426` and `e2b237926` and retains every
collection site from both parents (`docs/flushfix3/merge-rows.json`). The
shared padding conflict keeps wave 10's grouped-record count at byte 1318
and puts a saturating range count at 1319; saturated releases recount live
ranges before publishing a smaller count. FLUSH's group count now pairs its
cold install with wave 10's common unlink decrement. Neither locked size grows.

Before changing collapse, the merged binary passes all 14 flushfix2 directed
rows (112 target legs and 14 oracle legs), both lifecycle/replay units, and
both idle-deadline rows. The partial gate reports 19 passes including its
release row, zero failures. Receipts: `docs/flushfix3/merged-directed.json`
and `merged-directed-observations.json.gz`.

F2 is this merged, pre-collapse binary: it includes the separately proven idle
wake repair, and retains flushfix2's quadratic slow collapse. Its hash is in
`docs/flushfix3/f2.sha256`. The unmodified older failure control remains
separately identified as `f2-original`.

The initial headline/F2 scope comparison has 12 positive MGET/MSET deltas
out of 80 comparisons; scalar GET/SET/INCR add none. This is an explicitly
failing intermediate zero-tax check, to be superseded by the final counts.

### Bounded slow collapse

`src/store/flush.cc` builds a temporary first-occurrence index on the owner,
before mutating any resident or predecessor. It visits the later chain twice,
the physical slots once, and the index once to retire first predecessors.
Physical deletion uses the already-known slot, preserving erase accounting
and the existing armed-slot publication/QSBR order without another table probe.
The no-post-record fast path, range resolution, snapshot COW gate, WATCH,
blocked-reader reprobe, poison lifetime and AOF GroupFlush are unchanged.

Hash probing stops after 16 slots. Overflow uses a compressed bitwise tree over
the full hash, namespace and length-delimited key bytes. A descent visits
strictly increasing bit positions, bounded by 72 + 9L for maximum key length L.
Thus collisions cannot introduce a P-dependent unbounded chain scan. For fixed
key lengths the work is O(C + P + R), where R is the later zero-key range/header
population; counting key bytes makes the length factor explicit. The ordinary
case is O(C + P), with O(P) temporary memory allocated only on slow collapse.
Scratch allocation failure defers before mutation and preserves the decision.

Collapse remains one owner turn. Slicing would require keeping the index valid
across new installs, rehashing and snapshot progress, adding a separate lifetime
protocol. This change removes the repeated chain walks while retaining existing
owner scheduling. It supplies a work bound, **not a wall-clock writer-stall
bound**. No reader barrier, reader retry or seqlock is introduced; readers keep
the range resolver and existing QSBR/poison rules. The owner must judge the
remaining linear turn with the requested populated writer-wait instrument.

Serverless fixed-table observations, identical in both namespaces:

| Later occurrences P | POST visited entries | Exact full F2 visits |
|---:|---:|---:|
| 1,000 | 2,251,766 | 525,838,076 |
| 10,000 | 1,971,160 | 5,293,943,576 |
| 100,000 | 3,055,080 | 57,429,998,576 |
| 1,000,000 | 11,928,554 | 1,024,290,548,576 |

C=1,048,576 physical slots, 524,288 old residents, disjoint later delete
occurrences. Scratch power-of-two occupancy explains the small non-monotonic
first two observations; every observation satisfies 96(C+P). The counter charges
record visits, index initialization/probes/tree visits, physical slots and final
index traversal; it is not an instruction or latency measurement.
F2's full count is the exact closed form C + residents*P + P + P(P+1)/2 for this
fixture. Full quadratic walks are NOT RUN: the actual F2 function is instrumented
only to count visits and stop at 96(C+P)+1, falsifying all four sizes in both
namespaces. The throwaway images are never production arms.

The gate's two new serverless rows also check full-hash collisions, duplicate
keys, prefixes/NUL bytes, namespace identity, scratch OOM/retry and 600 live
ranges. Together with the two unchanged flushfix2 units, the first work gate
passes five rows including release, zero failures. Exact receipts and negative
control construction are in `docs/flushfix3/work/`. `tests/gates_test.py` passes
all 73 tests on the merged harness.

All builds and correctness children use CPUs 0–15, server CPUs 0–7,
client CPUs 8–15, ports 20100–20199 and LC_ALL=C. Performance measurements
and the full iteration are NOT RUN: reserved for the maintainer.
