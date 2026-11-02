# Lane correctness and measurement record

## atomfix6

Base / PRE: `9d6ab5526f8fff0c8617e94cf20fa837e15ab0f8`.
Worktree: `/home/user/Projects/cx-atomfix6`; branch `cx-atomfix6`; no push.
All builds and correctness processes use CPUs 74-86. Correctness server ports
are restricted to 21700-21799, with `LC_ALL=C` on every boot.
No throughput measurements or full iteration gate are authorized for this lane.

| Item | PRE witness | POST result | Mechanism changed | Residual |
|---|---|---|---|---|
| AT5.1 / AT5.2 | Direct audit schedule: 8/8 torn reads and 8/8 lost winners in each namespace | 0/8 torn, 0/8 lost in each namespace; both sanitizers pass; final live matrix 0/22,735,280 torn MGETs | Reject prefix collapse if any retained decided lower-ticket occurrence overlaps a selected key | Broader job proofs in progress; MVCC owner signs off at landing |
| S1-SURVEY-MSET8 | 256 held MSET8 tasks: eight passes, 8 polls, 2,019 parked-list visits, in both modes/namespaces | Eight passes, 64 head polls, zero follower scans; all 256 tasks remain held. Queue lifetime ASAN/UBSAN and TSAN pass | Per-connection park index / oldest-operation polling, bounded to the ordinary owner batch | Atomic-0 scopes unchanged; completed hot-cell performance remains maintainer-owned; AT5.3/AT5.4 unchanged |
| AT5.10 | All 8 PRE live arms fail; direct collapse and park units fail | Both engines pass 21/21 directed gate rows, 16 live arms total; captures armed and restart values exact | 12 serverless + 8 live rows | DQ=+20, DF=+20; EXPECT constants untouched |
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
All layout assertions still pass: Op 336, Client 1984, ThreadCtx 1408, Shard 1440,
FlatStore 944, Rob<64> 192, AtomicEntry 144 and Config 624 bytes. ExLoop remains
5856 bytes and FusedExLoop 5864; the indexed queue remains 80 bytes and its
counter block remains 128 bytes.

The PRE park fixture compiles the unchanged PRE scheduler with only two observation
increments in a private source copy. Renamed fixture instantiations prevent linked
weak production copies from hiding those observations. It constructs actual MSET8
scatter tasks and actual own-connection undecided store records. Its assertions
fail on PRE and pass on POST without timing or throughput thresholds.

Instruction preservation: `docs/atomfix6/counts/comparison-final.json` contains
all 80 PRE/POST command scopes. Every one of the 40 atomic-0 scopes is exactly
unchanged: GET/SET/INCR/MGET/MSET, 1s/2s, normal/db0, batches 1/32. All 16 atomic-1
MGET/MSET uncontended scopes are also unchanged. These command scopes use
read-local 0; MGET/MSET touch eight shards with 64-byte values. The live
correctness matrix separately covers read-local 0/1. The scope follows all executable
production functions, including outlined STL wrappers, excluding fixture glue
and shared-library internals. These are instruction counts, not cycles or rates;
they do not establish a throughput result or price asynchronous reclamation.
The initial candidate added 8 instructions per atomic-0 DB0 MSET. The cold guard
increased GCC's initial IPA size by 158 (131034 -> 131192); changing that unit's
budget from 165926 to 166084 restores the PRE xshard_execute body and all scopes.
The derived budget and both neighbouring trials are retained in `budgets/`.

Atomic-1 uncontended executable instructions, per complete traced batch (the
scopes exclude fixture glue and shared-library internals as above):

| Namespace | Command | Mode | Batch 1 PRE / POST | Batch 32 PRE / POST |
|---|---|---|---:|---:|
| normal | MGET | 1s / 2s | 10,174 / 10,174 | 324,390 / 324,390 |
| normal | MSET | 1s | 16,991 / 16,991 | 962,174 / 962,174 |
| normal | MSET | 2s | 16,659 / 16,659 | 951,550 / 951,550 |
| db0 | MGET | 1s / 2s | 10,044 / 10,044 | 320,230 / 320,230 |
| db0 | MSET | 1s | 16,376 / 16,376 | 897,854 / 897,854 |
| db0 | MSET | 2s | 16,030 / 16,030 | 886,782 / 886,782 |

`docs/atomfix6/contended/comparison.json` prices a separate held-predecessor
scheduler slice, using actual MGET8/MSET8 groups, eight connections and eight
owner passes. It is not a completed-command count: no held command can finish.
At depth 32 PRE polls 8 tasks, POST polls 64 heads, with all 256 tasks still held.
MGET takes 20219-20221 PRE versus 27856-28608 POST executable instructions over
those passes (2527.375-2527.625 versus 435.25-447 per poll); MSET takes 20265-20267
versus 27216-27968 (2533.125-2533.375 versus 425.25-437 per poll). Depth-1 and all
individual mode/namespace observations are included. These final costs use unmodified PRE, without the witness-only observation
increments; PRE poll cardinality comes from the separately instrumented witness.
POST does more work per pass because it polls eight heads rather than one task.
Hash-index probe costs can vary with allocation addresses. Completed contended operation cycles/IPC remain
for the maintainer's matched-load measurement.

Gate inventory: 12 serverless rows (6 collapse, 4 parked-head, 2 index-lifetime)
plus 8 live rows, all collected before the quick-tier exit. Both namespaces'
parked-head rows additionally run the complete instrumented owner/scatter code
with read-local 0/1 under ASAN/UBSAN and TSAN; these are assertions within those
existing rows. The final expanded unit job passes 13/13 including its build row;
all 24 parked-head runs report 64 polls, zero follower scans and 256 held tasks.
Per-run logs and counts are in `proof/expanded-units-final/park-results.json`.
**DQ=+20, DF=+20**. Maintainer-owned EXPECT_QUICK=1046 and EXPECT_FULL=1063
are untouched; the new totals should be **1066 / 1083**. Collection is at
`tests/gate.sh`'s `collect_job atomfix6_units` and following eight-arm loop,
at lines 6575-6578, above the quick-tier exit at line 6919. The gate planner now permits one unchanged
8-server/2-load slot for selected correctness jobs on this 13-core allocation;
complete/performance gates retain their 16-core minimum. Its positive and
negative planner tests and `tests/gates_test.py` cover that distinction.

The original live witness matrix (before the compiler-only budget correction)
failed every PRE arm. Its POST matrix passed 8,601,504 MGETs, with zero torn pairs,
zero at-rest tears and zero restart mismatches, including an armed capture/read
window in every arm. `pre-live-results.json` and `post-live-results.json` retain
all per-phase counts. The final release also passes the fresh two-engine matrix below. Redis 7.4 also passes the same live detector;
`docs/atomfix6/oracle/result.json` records its counts.

The eight PRE live arms counted 83,620 torn pairs in 6,132,976 MGETs. One of 48
frozen pairs remained torn through SAVE/restart in each of the 1s/read-local-0/DB1
and 2s/read-local-0/DB16 arms. The original T10 wide-group detector also failed PRE:
1,099 torn pairs in 1,059,840 MGETs in 1s. These are observed correctness counts,
not rates or throughput comparisons.

Maintainer measurement request (NOT RUN by this lane): use the gate's own ABBA
instrument and matched offered loads, quiet box, LC_ALL=C. Preserve cell geometry,
seeds, affinity and offered load across each PRE/POST and PAD-A/POST-layout pair.
Run the 14 generic cells in `docs/lbplanner/generic-cells.txt`, plus 2s GET/SET
at p1/p32. Also run atomic-1 MSET8/MGET8 at p1/p32 in 1s/2s, read-local 0/1,
databases 1/16, uncontended and overlapping hot keys. Include the survey's exact
`strings-MSET8-n100-p32` hot cell and T01 private/rotate shapes in both modes.
Record rate at matched load, cycles/op, instructions/op and IPC, plus park polls,
park visits, loop passes/op, admitted groups, queue depth and record visits.
Ordinary cells must have zero regression; hot-cell stalls must disappear without
changing ordering or losing a reply. Rate is the performance verdict; the finite
instruction counts explain only executed work. No throughput gain is claimed.

PAD-A is type **A (behaviour twin)**: PRE behaviour in the exact common
POST-layout image. `tools/execindex_pad.py` links POST first and a symbol-isolated
PRE second, then changes only main's five-byte entry jump. ELF sections and
symbols match exactly. Compare PAD-A with POST-layout, and separately compare
ordinary PRE with the smaller POST release. This controls the common image's
size/layout, not every executing PRE function's address relative to its POST
implementation; do not substitute it for the ordinary release comparison.
Full build commands, object digests and the five changed bytes are recorded in
`docs/atomfix6/pad-a.json`.

NOT RUN by authorization: full iteration, ABBA/performance measurements, the
atomic throughput floor, the memtier-based `flip_saturated` job, and the original
T01/T03 rate/perf load drivers. Also NOT RUN: `efficiency` (release timing/scaling
measurements) and the full gate's open-loop tailgen client-LB row (requires its
16-load-core measurement allocation). Their correctness mechanism is covered by the
held-predecessor serverless witness, ordinary FLIP rows and the pair detectors;
this is not a claim that their performance criteria passed. The maintainer owns
those measurements. T07/T08/T10/T15/T16/T17 detectors run with only lifecycle
substitution (CPU74-81, port21760, 16 shards, 6:2 split, selected binary); original
source hashes and exact arguments are retained with each audit result.

| Arm | Artifact | SHA-256 |
|---|---|---|
| PRE | `build/pre/tomokv` | `b09a48348a2f8483f4cf53a07801483edf4962853ee031310b9839da9dfc91ae` |
| POST | `build/tomokv` | `a0c8b0d8678e7732bcef579972b35dbb1071ddfdb2e741900d3f4892918d421c` |
| POST-layout | `build/atomfix6/arms/POST-layout` | `7c9db23622a3e3aadb48664f9c9acafdfef8e681a3ffba3a53c59546900581d8` |
| PAD-A | `build/atomfix6/arms/PAD-A` | `5a5258682210fe3b09544eb6407b648651fc0420c562f3df32efc45d80539112` |

Release `.text`: PRE 9,021,623 bytes; POST 9,027,287 bytes (+5,664).
Both common-image arms have 18,048,551 bytes of `.text`. No PAD-B was built.
The final gate harness tests pass 77/77 (396.099 s); the earlier 229.374 s
run also passed. These are correctness runtimes, not throughput measurements.

Completed auditor reruns: 14 POST detector invocations, 3,898,928 counted MGETs,
zero torn pairs/errors, and twelve T17 rounds with 0/16 pairs differing at rest
in every round and pending records draining to zero. Native T17 prints no MGET
denominator, so its rounds are not included in that read total. T16 restored both
dumps with 0/16 inconsistent pairs. T15's capture phases had 0/31,872 (1s) and
0/23,328 (2s) torn reads, with capture samples observed in both. Exact per-case
counts are in `docs/atomfix6/audit/counts.json` and the original result logs.

The complete-owner ASAN run found a fixture teardown leak from calling destroy
on prepared-but-never-executed scatter states. The fixture now removes all held
tasks and calls the existing unpublished-group cancellation arm, which releases
prepare-time owner completion pins. Its observed window and production behavior
are unchanged. Final ASAN/UBSAN and TSAN parked-head rows pass in both modes;
contended instruction receipts were regenerated after that fixture correction.

Final-release live matrix, through `atomfix6-live-*` jobs (each row: steady,
wide eight-shard MSET, BGSAVE, at-rest SAVE and restart). Every row has zero torn
pairs in every phase, zero at-rest inconsistencies and zero restart mismatches.
Capture reads count only replies sampled while capture progress was observed.

| Engine | Mode | Read-local | Databases | MGETs | Capture-overlap MGETs | Torn / rest / restart |
|---|---|---|---|---:|---:|---|
| uring | 1s | 0 | 1 | 1,770,816 | 703,616 | 0 / 0 / 0 |
| uring | 1s | 0 | 16 | 2,054,880 | 953,248 | 0 / 0 / 0 |
| uring | 1s | 1 | 1 | 1,941,488 | 915,552 | 0 / 0 / 0 |
| uring | 1s | 1 | 16 | 1,188,752 | 237,264 | 0 / 0 / 0 |
| uring | 2s | 0 | 1 | 1,120,640 | 69,936 | 0 / 0 / 0 |
| uring | 2s | 0 | 16 | 1,279,680 | 101,872 | 0 / 0 / 0 |
| uring | 2s | 1 | 1 | 973,968 | 62,208 | 0 / 0 / 0 |
| uring | 2s | 1 | 16 | 1,000,416 | 62,432 | 0 / 0 / 0 |
| epoll | 1s | 0 | 1 | 1,673,856 | 534,144 | 0 / 0 / 0 |
| epoll | 1s | 0 | 16 | 2,222,720 | 1,040,912 | 0 / 0 / 0 |
| epoll | 1s | 1 | 1 | 1,213,584 | 243,392 | 0 / 0 / 0 |
| epoll | 1s | 1 | 16 | 1,940,464 | 835,872 | 0 / 0 / 0 |
| epoll | 2s | 0 | 1 | 1,149,024 | 128,464 | 0 / 0 / 0 |
| epoll | 2s | 0 | 16 | 1,161,952 | 88,336 | 0 / 0 / 0 |
| epoll | 2s | 1 | 1 | 1,031,152 | 70,176 | 0 / 0 / 0 |
| epoll | 2s | 1 | 16 | 1,011,888 | 91,392 | 0 / 0 / 0 |

`make -q` passes for all 55 primary targets in `job_production_units`, and
for `make all`. The gate helper also built its mdbqsbr live controls and blockfix
auxiliary targets. Target inventory and individual freshness results are in
`docs/atomfix6/production-{targets.txt,freshness.json}`. The broader serverless
job group passes 54/54 rows; detailed per-job ledgers are retained under `proof/`.

All 18 AT412 jobs completed successfully in the broad atomic group, including
their complete built-in matrices; T6 and T10 each passed all 27 legs.

Verification history is retained, including superseded attempts. An initial
serverless group was intentionally stopped during a build after the compiler
budget correction (exit 130, no scored rows); `units-final` supersedes it. An
earlier directed-unit attempt reported ten freshness failures after the config
comments changed during the build. Rebuilding the affected targets removed those
stale-artifact failures; the final two-engine directed jobs each pass 21/21.
These attempts are not included in the final pass counts.

To stay below the disk budget while retaining sanitizer and control artifacts,
GNU objcopy compressed debug sections in four generated control-object trees.
Every allocated ELF section was hashed before and after and stayed identical;
object timestamps are preserved and no executable instruction changed. The
per-object before/after hashes are in `compressed-control-objects.json`. Release
PRE/POST objects and binaries were left untouched.

The initial broad live FIFO run overlapped debug-section compression on the lane
cores and failed latency bounds in several legs despite zero reported ordering
violations and exact final values. The latency failures are retained, not waived.
The complete isolated controls then ran with no concurrent lane compilation or
artifact compression. PRE passed 13/16 legs and failed three maximum-latency
assertions (30.6, 50.0 and 53.1 ms against 20 ms); POST passed 15/16 and failed
one (41.3 ms, databases 16 / 2s / atomic 1 / epoll). All 32 isolated legs had
exact final values and zero ordering violations; all met their p99 bounds.
The latency criterion remains unmet. No threshold was changed; both the
initial failures and the isolated-control failures remain in the record. `fifo-comparison.json` retains every leg and its original assertions.

The broad atomic group completed 133 passing rows and one failed FIFO latency
row. This includes all 18 AT412 jobs, the atomic/torn/RYOW/owner-hazard batteries,
both group modes, execfair, exec1s, FIFO units and all other transaction-order
jobs. The isolated PRE/POST FIFO controls above retain that residual explicitly.

The separate fused atomic group passes 45/45 rows. After expanding the parked-head
fixture, `tests/gates_test.py` again passes 77/77 (185.025 s). The expanded PRE
fixture fails as required in all eight mode / namespace / read-local combinations;
each observes 8 polls and 2,019 scans over eight owner passes with 256 tasks held.
Its logs and binary hashes are in `park-pre-expanded/`.

A second debug-only compression pass covered 157 generated unit/sanitizer objects
and saved 513,418,136 bytes. Allocated sections and modification timestamps stayed
identical; `compressed-unit-objects.json` records every before/after digest.

The two common-image PAD arms were subsequently debug-compressed before their
first live validation. ELF program headers, every allocated section (including
its address and file offset), section/symbol equality between twins, and the
five-byte-only entry difference were all rechecked. The table above gives their
final hashes; `compressed-pad-images.json` retains the uncompressed hashes and
checks. This reduces disk use without changing their loaded image or behavior.

The first expanded sanitizer attempt exposed a fixture link omission: DB0's
scripting objects delegate Lua's process-wide implementation to the normal
namespace. The DB0 sanitizer link now includes that namespace's fully instrumented
objects, while linking the C helpers only once. The failed link attempt and its
four red parked-head rows remain in the feature-group record; the corrected
complete unit job passes 13/13. Normal-namespace sanitizer runs in that earlier
attempt already pass both read-local settings.

The feature group records 299 passing rows and five failures: the four superseded
fixture-link failures above, plus `wave14_order` publication-order assertions.
The full PRE control reproduces all 144 candidate-case failures. Both PRE and
POST have 144 sequence mismatches, 74 slowlog-order mismatches and zero reply
mismatches; their nine Redis oracle cases pass. Five candidate event orderings
differ between runs, so these are matching failure counts, not identical traces.
`publication-order-comparison.json` retains the differences. This baseline issue
remains unresolved; this lane does not alter the CD5.5/CD5.6 publication mechanisms
assigned to txnfix4. No ordering assertion was weakened.

The default persistence group passes 228/228 rows, including both AOF and snapshot
engines, BGSAVE under scripts/EXEC, save/restart, FLUSH, AOF frame/commit order,
fsync/rewrite matrices and WAIT AOF. Its fused generic-boot follow-up passes
158/158 rows, including the ASAN atomic batteries and reply-off/zero-copy jobs.
The separate fused notification/MULTI job passes 7/7.

Placement records 132 passing rows and one `flipfix6` fixture failure. The required
CPU74-81 / 6:2 geometry has IO thread IDs 0,1,2,3,6,7; the fixture hard-codes 0-5.
All 56 session witnesses therefore fail to arm, and its short-circuited scale
stage does not run. Two FLUSH/FLIP sibling legs also see the approved close refusal
when one storm thread closes its connection before the final FLIP drains. Original
results are retained in `proof/placement-uring-default/flip-results.json`. The
unchanged PRE control reproduces all 56 unarmed session cases and three rejected
close refusals in the FLUSH/FLIP siblings. The fixture now discovers all six IO
roles from DEBUG LBSIGNALS, preserves the session-move assertions, and keeps the
FLUSH peer open until the final FLIP drains. Its accepted errors and time limits
are unchanged. The gate runs both session scales even if the first fails; no
new row is added. The corrected POST job passes both gate rows (including its
release row), all 56 primary session legs, all 16 larger-scale legs and all 10
FLUSH/FLIP sibling legs. `proof/flipfix6-POST-topology/flip-results.json` retains
the role coverage, transfer counts and timing assertions for all 82 legs. All eight
eviction jobs, stationary LB in both modes, other FLIP jobs, read-local jobs and
35 feature-matrix cells in this group pass.

Supplemental blocking-MULTI, FLUSH notification, no-touch, AOF-load, MISCONF,
database-default and witness-contract jobs pass 25/25 rows. The io_uring
differential group passes 6/6 gate rows, including 235/239 split comparisons,
230/234 armed-fused comparisons and 16 mode-equivalence comparisons. Its native
seed inventory is 7,19,20,23,21. The armed-fused driver deliberately does not run
the SORT suite because that fixture requires split 6:2 geometry; both split arms
run it. No custom differential seed or suite reduction was used.

Completed passing persistence jobs retained about 2 GB of dump/AOF test data.
Those generated data files were hashed and retired after job completion to keep
`build/` near 14 GB; all logs, results, required binaries and source objects remain.
`retired-persistence-data.json` records the paths, sizes, hashes and passing job
completion status for every removed payload.
