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

The initial fix is proven before the merge. Final-binary idle observations are
reported separately below; the initial pass does not erase a later failure.

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
out of 80 comparisons; scalar GET/SET/INCR add none. This failing intermediate
check is retained in `counts/comparison-f2.json` and
`counts-before-cold-isolation.json.gz`.

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
These bounds concern record selection and traversal; existing object destruction
and expiry-index bookkeeping retain their existing costs and are not charged
by the visited-entry counter.
Scratch allocation failure defers before mutation and preserves the decision.
An already-decided FLUSH then needs memory to become available before it can
complete; this is a temporary-memory tradeoff, not an OOM completion guarantee.

Index keys borrow the retained later records: copied keys for plain records,
installed candidate objects or tombstone anchors for grouped records. Physical
objects named by a later record are preserved during the slot scan. The final
retirement pass reads only predecessor pointers, and retires only the first
pre-flush predecessor for each key; it performs no further key comparisons.
Later predecessors and their snapshot histories remain intact.

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
keys, prefixes/NUL bytes, namespace identity, scratch OOM/retry, repeated-key
snapshot histories and 600 live ranges. Together with the two unchanged flushfix2 units, the first work gate
passes five rows including release, zero failures. Exact receipts and negative
control construction are in `docs/flushfix3/work/`. `tests/gates_test.py` passes
all 73 tests on the merged harness.

### Ordinary instruction scope

All 80 final comparisons add **zero executed instructions** relative to the
headline: GET/SET/INCR/MGET/MSET, batch 1/32, modes 1s/2s, database images 1/16,
atomic 0/1. The exact PRE/POST table is `docs/flushfix3/instructions.md`; JSON
counts include per-function breakdowns, fixture build commands and probe hashes.
Counts include executed NOPs in named production bodies and exclude library
callees and fixture glue. They are not whole-process instructions or cycles.
The established executor fixture sets read-local=0; connection-side read-local
instruction scopes are NOT RUN. Live armed correctness is tested separately.

The merge required reselecting scatter inline budgets (auto=14 normal, 18 DB0),
keeping FLUSH prepare/execute cold, and suppressing executed alignment padding
in normal scatter preparation, as already done for execution. The existing
script/FLUSH escape is marked unlikely; no new ordinary-path discriminator is
added. Rejected compiler trials remain in `docs/flushfix3/budget-counts/`.
These code-layout effects require the ordinary null merit; instruction counts
alone are not a performance conclusion.

### Frozen delivery arms and owner's merit request

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE, exact `e2b237926` | `build/flushfix3/pre/tomokv` | `0c9e431af327cddb0113d7a504591cf38ea895893ecacf7419f6c5328ae70d5e` |
| F2, merged pre-collapse `a42e527b0` | `build/flushfix3/f2/tomokv` | `de33a1e3d60f876f29a20b0ebacf3a8e9a45fb41146d71c8cebba8ad8fa4cb03` |
| POST, production source `a9e45b822` | `build/flushfix3/post/tomokv` | `a9469f15f28a374f456f7e431c309a70fb32487293e84033d3895a9274d0427a` |
| PAD-A | `build/flushfix3/pad-a/tomokv` | `c6f9664b2a96a5fcf55e2b635dd14bf9492d7c885a0c42ce43af69b16dba0f02` |

PAD-A is **(A) behaviour twin**: PRE's legacy FLUSH routing with POST's exact
ELF section sizes, function addresses and symbol layout. Four three-byte patches
disable only the cold FLUSH predicate and snapshot continuation pump in both
images. POST budgets and dormant range/index code remain. The byte restoration
check and exact offsets are in `docs/flushfix3/pad-a.json`; arm sizes and hashes
are in `arms.json` and `arms.sha256`. F2 includes the step-0 wake fix and is
therefore the reference for the collapse change, not the original idle-stall
negative control.

`.text` sizes are PRE 8,659,975, F2 8,768,503, and POST/PAD-A 8,773,639 bytes:
POST is +5,136 bytes over F2 and +113,664 over the headline. PAD-A preserves
every section and symbol address exactly.

Use the `cx-flushmerit` instruments (inspected at `ee7c0b583`) and the gate's
own measurement instrument on the owner's quiet box. This lane runs none of
these campaigns. Keep identical geometry and offered load across compared arms.

- `calib/flush-writer-wait.py --population 1000000`: POST versus F2 and PRE,
  all mode/image/atomic/SYNC/ASYNC cells and same-key/disjoint-key/no-flush
  schedules, 16 SET writers at pipeline 1 and 10 Hz FLUSHALL. Freeze a load
  sustainable by every arm. Decide the collapse improvement by worst SET RTT
  and p99.9 per cell, retaining all individual observations and scheduled-send
  lag. Require actual slow collapses/post versions; an unopened window cannot
  support the bound's merit. The first flush is populated; record each later
  population and do not describe it as replenished. Client RTT is an upper
  bound, not a pure placement-wait duration. Compare POST/F2 and POST/PRE in
  paired ABBA campaigns if using the inspected instrument: its third-arm
  metadata accepts only PAD control kinds, so PRE must not be mislabeled PAD.
- `calib/flush-latency-merit.py --populations 1000000`: POST/F2/PRE over the
  same product, at least 100 nonempty observations per arm/cell, with fresh
  seeding outside each timed interval. Retain p50/p95/p99/max and reclamation.
  Use paired campaigns as above, and a POST/PRE/PAD-A campaign with
  `--third-kind behaviour-twin` when attributing layout effects. An optional
  empty-population repeat uses at least 1,000 calls; the directed idle row is
  a correctness deadline witness, not a quiet-box latency distribution.
- The 14 generic cells plus split GET/SET at p1/p32 (`h53/h54/h21/h22`) are
  frozen in `docs/flushfix3/merit.cells.txt`, with source hashes in
  `merit-cells.json`. Run POST/PRE/PAD-A with the gate's normal ABBA/matched-load
  rules; retain cycles/op, IPC and instructions/op. The gate's existing
  regression verdict decides this 18-cell null. No throughput gain is claimed.

### Row accounting and verification status

The added collections are `tests/gate.sh:6025` (two idle rows) and `:6026`
(two work rows), before the quick exit at `:6334`: flushfix3 DQ=+4, DF=+4.
The inherited flushfix2 collections at `:6027` and `:6028` contribute 14+2 rows
at the same tier. Cumulative delta over `e2b237926` is DQ=+20, DF=+20; the owner
would change 946/963 to **966/983**. EXPECT constants were not edited by this
lane; their incoming values came from the requested merge.

Final verification is in progress through `tools/flushfix3_verify.py` and the
gate's selected-job interface. The final idle run has one failed sample:
DB1 / 2s / uring / atomic1 / FLUSHALL ASYNC took 9,079,092 ns, over 5 ms.
All original fused-stall legs pass. This failure is retained. One complete fresh
idle recheck, with builds and artifact processing stopped, passes all 64,000
calls at the same bound (maximum 1,033,161 ns);
`docs/flushfix3/idle-final-recheck.json` records every
form's count and maximum. No tolerance or retry-until-green rule was added.
The final work rows pass both namespaces and their F2 falsifiers. The 73 gate
self-tests pass again after exposing scriptfix's engine/atomic selections and
the AOF engine controls. `make -q` reports all 61 requested production and FLUSH
targets fresh, including `all`; exact commands and hashes are recorded in
`docs/flushfix3/production-freshness.json`.

The broad selection was interrupted **between** jobs after 54 completed jobs
and 384 passing rows, zero failures, to respect the task's load-generator
restriction. No test was interrupted and `flip_saturated` never started.
`broad-interruption.json` preserves the exact completion inventory. The resumed
selection passes another 247 rows. After removing repeated prerequisites, the
broad union covers 96 distinct jobs and 630 passing rows, zero failures
(`docs/flushfix3/broad-coverage.json`). FLIP's `flip_saturated` row invokes
`memtier_benchmark`; it is NOT RUN pending the owner's clarification, while the
other FLIP jobs remain selected. It is not silently counted as passing.
The additional epoll selection completes with 268 passing rows, zero failures;
fused persistence and the remaining explicit mode/engine controls are still
running before the standard-seed differential selections.

Superseded compiler probes, source trees and logs were removed after retaining
their hashes and counts. Large persistence images from completed passing jobs
were also hashed and removed; their ledgers and comparison results remain.
The pruning manifests are in `docs/flushfix3/pruned-*.json`.

Inherited sibling findings in `MEASURE-REQUEST-flushfix2.md` remain relevant:
the historical FLUSH+FLIP abort and DEBUG RELOAD/LOADAOF visibility defects were
demonstrated on that lane's PRE and POST. This change does not claim to repair
those mechanisms. Current-branch job results and any new failures will be
recorded with their exact coverage; a partial selection is not a full gate
receipt.

All builds and correctness children use CPUs 0–15, server CPUs 0–7,
client CPUs 8–15, ports 20100–20199 and LC_ALL=C. Performance measurements
and the full iteration are NOT RUN: reserved for the maintainer.
