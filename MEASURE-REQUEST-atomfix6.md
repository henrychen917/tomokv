# Lane correctness and measurement record

## atomfix6

Base / PRE: `9d6ab5526f8fff0c8617e94cf20fa837e15ab0f8`.
Worktree: `/home/user/Projects/cx-atomfix6`; branch `cx-atomfix6`; no push.
All builds and correctness processes use CPUs 74-86. Correctness server ports
are restricted to 21700-21799, with `LC_ALL=C` on every boot.
No throughput measurements or full iteration gate are authorized for this lane.

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| AT5.1 / AT5.2 | Direct audit schedule: 8/8 torn reads and 8/8 lost winners in each namespace | 0/8 torn, 0/8 lost in each namespace; ASAN/UBSAN and TSAN pass | Reject prefix collapse if any retained decided lower-ticket occurrence overlaps a selected key | Live detector and full job proofs pending; owner signs off at landing |
| S1-SURVEY-MSET8 | 256 held MSET8 tasks: eight passes, 8 polls, 2,019 parked-list visits, in both modes/namespaces | Eight passes, 64 head polls, zero follower scans; all 256 tasks remain held. Queue lifetime ASAN/UBSAN and TSAN pass | Per-connection park index / oldest-operation polling, bounded to the ordinary owner batch | Live and instruction-count proofs pending |
| AT5.10 | Pending | Pending | Directed gate rows | EXPECT constants remain untouched |
| AT5.8 | Comments claimed atomic 0 was allocation-free | Claims now describe optional write groups, retained EXEC/script/read-cut machinery and winner preservation | `tomokv.conf`, `config.h` comments only | Base still implements live CONFIG SET atomic; this lane does not change that runtime policy |

The record witness uses real FlatStore install, resolve and collapse methods.
It covers an undecided or too-new unrelated boundary, replacement or tombstone
winners, read-local off/on, and both compiled namespaces. Unused external
subsystems fail closed in the fixture. ASAN/UBSAN runs use leak detection and
halt-on-error. TSAN initially refused its randomized address mapping; the gate's
own `setarch x86_64 -R` convention runs both units successfully. Logs are in
`docs/atomfix6/`.

Preservation-floor argument: the existing selection still requires every
non-aborted selected epoch to be strictly below the published reader floor and
at or below the cleanup cutoff. The new guard only refuses reclamation; it never
expands that set, changes a ticket, mutates a reader, or frees an extra object.
Before removing a selected record's ticket, it compares against every decided
retained occurrence of that key, not merely the first occurrence. The maximum
selected / minimum retained test skips key comparisons when tickets cannot
invert. Aborted records cannot win. Undecided records cannot later publish a
ticket below an eligible winner: cleanup's safe cutoff excludes unpublished
reservations, and callers load that cutoff before the reader floor. Same-client
ticket repair is bounded by the selected maximum; conservative pairwise checks
retain that ordering too. Existing collapse arms and QSBR retirement remain
unchanged. Namespace range suffixes are checked for coverage as well.

PRE, POST and PAD-A hashes, command-scope counts, complete correctness receipts,
DQ/DF and maintainer measurement cells will be appended before delivery.

Parking refinement: both deferred and bounded-retry queues retain a global FIFO
plus an owner-local index by Client and ROB operation ID. Predecessor checks keep
the existing exact key/whole-owner predicate but visit only older operations of
that connection. Deferred service polls at most one head per connection per pass,
bounded by the existing executor batch. Equal-operation sibling fragments rotate
so a destination cannot indefinitely hide the source it needs. Records and group
decisions are unchanged; followers still cannot install behind their own undecided
overlapping group. Existing writer promotions and transaction-boundary removals
update both indexes. Removal precedes execution/forwarding, so no index follows a
task into another owner or outlives its ROB. State is allocated only on a park;
the queue retains the old deque's size/alignment and empty-test field offsets.
The two shutdown-only park diagnostics occupy existing Exec1sCounters tail padding.

The PRE park fixture compiles the unchanged PRE scheduler with only two observation
increments in a private source copy. Renamed fixture instantiations prevent linked
weak production copies from hiding those observations. It constructs actual MSET8
scatter tasks and actual own-connection undecided store records. Its assertions
fail on PRE and pass on POST without timing or throughput thresholds.

Instruction preservation: `docs/atomfix6/counts/comparison-final.json` contains
all 80 PRE/POST command scopes. Every one of the 40 atomic-0 scopes is exactly
unchanged: GET/SET/INCR/MGET/MSET, 1s/2s, normal/db0, batches 1/32. All 16 atomic-1
MGET/MSET uncontended scopes are also unchanged. The scope follows all executable
production functions, including outlined STL wrappers, excluding fixture glue
and shared-library internals. These are instruction counts, not cycles or rates;
they do not establish a throughput result or price asynchronous reclamation.
The initial candidate added 8 instructions per atomic-0 DB0 MSET. The cold guard
increased GCC's initial IPA size by 158 (131034 -> 131192); changing that unit's
budget from 165926 to 166084 restores the PRE xshard_execute body and all scopes.
The derived budget and both neighbouring trials are retained in `budgets/`.

`docs/atomfix6/contended/comparison.json` prices a separate held-predecessor
scheduler slice, using actual MGET8/MSET8 groups, eight connections and eight
owner passes. It is not a completed-command count: no held command can finish.
At depth 32 PRE polls 8 tasks, POST polls 64 heads, with all 256 tasks still held.
MGET takes 28372-28374 PRE versus 27856-28608 POST executable instructions over
those passes (3546.5-3546.75 versus 435.25-447 per poll); MSET takes 28418-28420
versus 27216-27968 (3552.25-3552.5 versus 425.25-437 per poll). Depth-1 and all
individual mode/namespace observations are included. Hash-index probe costs can
vary with allocation addresses. Completed contended operation cycles/IPC remain
for the maintainer's matched-load measurement.
