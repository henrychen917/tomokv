## exec1s

The refinements implement X0–X6 of the owner’s EXEC design on PRE `83e0b809d`.
The historical lane stopped at `bd90f09de`. All of its pre-audit binary, runtime,
allocation and instruction receipts are VOID. The continuation below replaces
them; the deleted worktree and its archived images are not evidence.

| Arm | Frozen source | Behaviour |
| --- | --- | --- |
| PRE | `83e0b809d` | Baseline, including the inherited LAT-OFF-EXEC-1 cost |
| X1 | `f893d7432` | X0 counters plus registered ring fds and conditional fused EX-ring entry |
| X2 | `96624237a` | X1 plus repaired eager prefix cleanup, blind-group count and hash reuse |
| X3 | `2022b5374` | X2 plus guarded owner passes at fused rotation boundaries |
| X4 | `a8829929a` | X3 plus `TOMO_EXEC1S_WB`, isolated pending owner D5 |
| X5 | `6e1a805ed` | X3 plus participant storage and queued spec classification; X4 disabled |
| POST | `bd90f09de` | X5 plus directed test/tooling changes; X4 disabled |
| POST-layout / PAD-A | Rebuilt POST / PRE | Common-image type-A behaviour-twin pair |

No FIFO hand-off, connection shedding, transaction batching, co-location,
pipelined EXECs, or latency-tracking repair was added. D1–D10, amend1 and D4′
retain the boundaries in `docs/exec1s/rules.md`.

X1 retains the pass clock read. It services queued SQEs, owned CQEs, incoming
deferred task work and retained CQ overflow; ring registration is issuer-local.
X2 loads the completed cutoff before the reader floor and retains existing QSBR
retirement. Its two-byte owner update excludes the adjacent immutable reader
byte; the modulo-256 group count cannot select the fast exit when total live
records reach 256. The existing changed-field `publish_size()` call is restored,
including expiry/object-byte changes without a key-count change.

X3 hints contain no shard/client pointers and only select a complete guarded
owner pass. Normal polling remains the liveness backstop. X5 stays below the
approximately 60-site stop rule and changes no locked footprint. Claim-only
metadata shards receive storage slots without acquiring execution tasks.
REGISTER has no `exec1s D5` owner line; X4 is excluded from POST. Its separate arm
uses a MULTI-session ROB interval, retaining the EXEC barrier and interactive
MULTI/QUEUED replies. Historical Opus audit files are source-review context only,
not current execution receipts.

## exec1s-c

Worktree `/home/user/Projects/cx-exec1s-c`, branch `cx-exec1s-c`, starting at
`bd90f09de`; no push. Builds use `taskset -c 48-63`, `make -j16`. Correctness
servers use CPUs 48–55, clients 56–63 and ports 20400–20499. The harness socket
fixture uses `GATE_TEST_PORT=20498`. Individual gate jobs
retain their own explicit geometry overrides; ordinary boots use 16 shards and
6 IO / 2 executor threads. No performance workload or full gate iteration runs
in this lane.

### Rebuilt artifacts

All nine images (PRE, X1–X5, POST, POST-layout and PAD-A) are rebuilt. Records in
`docs/exec1s/arms.json` and `docs/exec1s/SHA256SUMS` identify current images.
`tools/exec1s_build.py` builds one frozen source snapshot at a time, constructs
its relevant probes, records hashes, then deletes that snapshot and object tree.
The POST production objects remain for the gate’s unit builds and freshness
checks. Step traces and completed probes are deleted after recording counts,
log hashes and probe-retirement bindings. Completed persistence jobs' large data
files were hashed before retiring 2.69 GB (`docs/exec1s/retired-data.json`); logs
and ledgers remain. The final build directory is below 30 GiB. X5 and POST match in all 30 allocated
sections other than the build-ID note; their different file hashes reflect debug
metadata/build ID (`docs/exec1s/x5-post-equivalence.json`).

**PAD-A is type A (behaviour twin):** PRE behaviour in exactly the same combined
text/data layout as POST-layout. POST is linked first, symbol-isolated PRE
second; PAD-A changes only the main-entry jump. Sections, symbols and function
addresses must match. The common image is larger than release POST. Use
POST-layout/PAD-A as the layout-controlled comparison and POST/PRE as the
release comparison; do not label PAD-A an exact-size twin of release POST.

### Replacement proof receipts

The authorized correctness run has finished. **Acceptance is not green:** one
standard-seed epoll comparison remains unresolved, and the allocation and X3
idle-instruction targets below are missed. Fresh results are in
`docs/exec1s/live-proof.json` and `docs/exec1s/live-job-results.json`. They bind the
POST hash, each job's completion/ledger/log, differential plans and completed
comparison inventories. These are individual-job results, not a full-gate receipt.

The first selected-family attempt was cancelled to replace the harness socket's
default ephemeral port with 20498; none of that interrupted attempt is counted.
The restarted run completed with 763 passing rows and two preparation failures.
`blockfix_registry` lacked the frozen POST cost-witness SHA sidecar; after
checking both source-built hashes and POST byte identity, its complete rerun
passed, including the instruction witness and all 24 live oracle legs.
`trackfix_order`'s private copy omitted the new `tools/assert_map.py` build
prerequisite. The repaired copy passed all 16 original live legs, 30 assertions
per leg. Hooks and assertions are unchanged. The original failures remain in
their ledgers and are linked to the passing reruns.

**Unresolved differential failure:** epoll, split, atomic 0, seed 22, `psfix`:
SAVE returned `Background save already in progress` after the both-peer idle
barrier, so the suite refused to compare the reply. SAVE/INFO and snapshot
admission are unchanged from PRE; a placement-transition refusal maps to the
same error. The actual Busy reason was not captured. This is neither classified
as a confirmed lane regression nor waived as a harmless retry. The failed case
and incomplete split-0 part remain failed; all other requested differential
parts finished. See `docs/exec1s/epoll-psfix-failure.json` and the retained failed
seed history. The remaining SAVE/BGSAVE assertions in that one case are
**NOT RUN**, because its first SAVE assertion aborted the case.

The first two supplemental CQ observer invocations each failed nine shutdown
receipt rows because the observer destructor wrote after `shutdown_report`.
Observer records now use separate per-thread files. Both complete instrumented
AOF reruns passed 57 rows with unchanged production bytes and shutdown assertions.
They observed 7,139,980 and 8,363,474 boundaries, respectively; each had 2,920 ring
records, with zero observed overflow or dropped completions. Fused EX-ring
records were present (596 / 884). The old failed attempts are preserved.

The Redis Tcl dependency passed both modes against the unchanged PRE manifest:
all 70 file/mode inventories and 3,286 required assertions match. Its existing
named `appendonly` block-setup error remains visible and checked exactly
(`docs/exec1s/tcl-manifest-verification.json`).

- X2: production TSAN owner-word helper, the old overlapping-write negative
  control, actual 256-live-group wrap/decrement checks, pinned-floor cleanup,
  and same-key-count statistics publication in both modes × atomic 0/1.
  **PASS:** repaired publication 4/4; restoring only the old guard fails the
  unchanged assertion 4/4; TSAN production leg passes and its wide-write child
  exits 66 with a data-race report; actual wrap/pinned-floor checks pass 8/8.
  Receipts: `docs/exec1s/publication-negative.json`, `docs/exec1s/word-tsan.json`.
  Temporary broken source and binary were deleted.
- Ordinary instructions: PRE, POST and PAD-A, 48 scopes each: GET/SET/INCR/MGET/
  MSET, batches 1/32, 1s/2s, both namespaces, MSET atomic 0/1. Counts include
  named linked production bodies; library callees and fixture glue are excluded.
  Exact data assertions are mandatory. No surrounding network or WB cost is
  implied by an ordinary-command result. **POST and PAD-A PASS, 48/48 each, max delta 0**
  against fresh PRE; 144 ordinary cases total (`docs/exec1s/command-counts.json`).
- Lever scopes: X1 idle rotation and EXEC owner; X2 eight same-shard EXECs through
  the linked production batch; X3 clear-hint idle rotation; X4 the parsed EXEC
  block’s WB decision after the ordinary visit allowance; X5 preparation/dispatch.
  All **52 lever scopes completed** (`docs/exec1s/lever-counts.json`). Allocation
  counts retain the complete `allocate_state`–`prepare_commands` scope. Probe
  hashes were checked before deletion (`docs/exec1s/probe-retirements.json`).
- POST live proof: the selected families and supplementary legs are complete
  with the unresolved differential failure above. `python3 tests/gates_test.py`
  passed all 73 tests. `make all` and all 47 literal `job_production_units`
  targets built; the additional live-control/cost targets also built. All 51
  final `make -q` checks pass (`docs/exec1s/freshness.json`).

Per-invocation row counts include dependencies and overlap; they are not a new
unique full-gate total:

| Invocation | Jobs | Passing / failed rows | Result |
| --- | ---: | ---: | --- |
| Selected families, complete restart | 177 | 763 / 2 | Two preparation failures, resolved below |
| Blocking/tracking complete rerun | 4 | 3 / 0 | PASS |
| Supplementary fused legs | 19 | 215 / 0 | PASS |
| Scripting atomic-0, each mode | 2 each | 3 / 0 each | PASS |
| Standard differential, uring | 6 | 6 / 0 | PASS: 954 comparisons |
| Standard differential, epoll | 6 | 5 / 1 | FAIL: `psfix`, split-0, seed 22 |
| Original CQ observer, each mode | 4 each | 48 / 9 each | Observer-output failures, retained |
| Separate-file CQ observer, each mode | 4 each | 57 / 0 each | PASS |

Both differential plans use permanent seeds 7, 19, 20, 23, 47 suites and four
repeat schedules; their rotating seeds are 21 (uring) and 22 (epoll). Epoll's
other parts passed: split-1 239 comparisons, armed-0 230, armed-1 234 and
mode-equivalence 16. Its split-0 inventory has 234 passing cases and the one
failed case; it has no completion receipt. Across the retained attempts there
are 21 failed gate rows: 20 resolved preparation/observer rows and one unresolved
differential row. No original verdict was rewritten.

`tools/exec1s_finish_proof.py` selects jobs through `tests/gate.sh`’s own partial
interface, preserving internal legs and watchdogs. No EXPECT-based full-gate
receipt is claimed. The Redis 7.4.10 oracle is from
`/home/user/Projects/redis`, commit `f103d127b9747965e28f20615ef790332661fc68`;
its fresh binary SHA-256 and identity are in `docs/exec1s/oracle.json`.

**NOT RUN (maintainer work):** `flip_saturated` and `atomic_floor` invoke memtier;
the `atomic_ryow` rate assertion is disabled with the gate’s existing
`GATE_PROOF_NO_RATES=1` partial-proof mechanism. Its finite correctness schedules
remain enabled. Full iteration, performance merit and load generators remain
with the maintainer. No missing performance leg is reported as a correctness pass.

### Design acceptance checks

Fresh complete allocation scope, two Local INCRs and two participants, both
namespaces (`docs/exec1s/allocation-comparison.json`):

| Check | PRE | POST | Verdict |
| --- | ---: | ---: | --- |
| 1s, 64 shards, bytes | 13,514 | 4,490 | FAIL: 0.332×, target <=0.25× |
| POST 2s/16 → 1s/64 shards, bytes | 4,315 | 4,490 | PASS: 1.041×, target <=1.2× |

The initial allocation alone is not substituted for this complete scope; POST
allocates participant arrays after discovery. The fresh X3 idle-rotation proof also misses its target:

| Namespace | X2 | X3 | Delta | Verdict |
| --- | ---: | ---: | ---: | --- |
| normal | 3,665 | 3,695 | +30 | FAIL: target <=+2 |
| db0 | 3,631 | 3,647 | +16 | FAIL: target <=+2 |

The scope is one actual linked production fused rotation, iteration [2,3),
with every hint clear. The unchanged fixture asserts that the rotation window
opened and that no extra owner pass ran. These misses are disclosed for owner
judgment; no ordinary-command or rate equivalence is inferred from them.

### Gate row accounting

This continuation adds no scored row: **DQ=0, DF=0**. The inherited exec1s feature
adds four rows: `collect_job exec1s` at line 5695, before the quick-tier exit at
line 5803, therefore **DQ=+4, DF=+4** relative to PRE. PRE already carries
execindex’s two rows beyond the stored 798/815 constants. The resulting inventory
is **804 quick / 821 full** (800/817 plus four), subject to owner integration.
`EXPECT_QUICK` and `EXPECT_FULL` are unchanged.

### EXEC instruction detail

Linked preparation/dispatch instructions (queueing is outside this scope):

| Namespace / mode | PRE / X3 | X5 / POST |
| --- | ---: | ---: |
| normal / 1s | 11,176 | 6,932 |
| normal / 2s | 8,776 | 6,932 |
| db0 / 1s | 9,992 | 5,846 |
| db0 / 2s | 7,592 | 5,846 |

The same-shard owner, idle and X4 WB counts and production/probe hashes are in
`docs/exec1s/lever-counts.json`. X4’s parsed-block WB predicate is checked against
the unchanged X3 decision in both modes and namespaces. All fixtures check exact
results after their count window; a count without successful assertions is rejected.

### Maintainer merit request

Use the current hashes, matched options and offered load, and the gate’s existing
per-cell null rules. Do not average away a failing cell. No throughput claim is
made by this lane.

1. `/home/user/Projects/calib/exec-merit.py`, **64 connections**, pipeline 4,
   **1s and 2s**, atomic 0/1, hot and uncontended. **POST versus PRE: 3 blocks**.
   The eight cells are `x1s_a0_unc,x1s_a0_hot,x1s_a1_unc,x1s_a1_hot,`
   `x2s_a0_unc,x2s_a0_hot,x2s_a1_unc,x2s_a1_hot`. Keep the harness’s four plain
   INCR clients in hot cells, placement, databases=1 and read-local settings.
   Explicit driver arguments: `--conns 64 --threads 16 --cells all --blocks 3
   --secs 20`. Its eight server cores use 1s/read-local=1/64 shards or
   2s/ratio=6:2/16 shards; key/client balancing and automatic FLIP stay off.
2. **Per-lever attribution: 1 block**, same eight cells and 64 connections:
   X1/PRE (includes X0 telemetry), X2/X1, X3/X2, isolated X4/X3, and X5/X3
   (X4 remains disabled). Run POST-layout/PAD-A as the type-A control. Record
   each arm separately; a one-block attribution result does not replace the
   three-block POST/PRE decision. Use the same driver arguments with `--blocks 1`;
   the first arm in each pair is `--candidate`, the second is `--reference`.
3. `/home/user/Projects/calib/exec-depth-sweep.py --binary build/exec1s-POST`,
   both `--mode 1s` and `--mode 2s`, atomic 0 and 1, cross/same-owner/same-shard,
   depths `16x1,16x4,32x4,64x4,128x4`, three blocks. X2’s same-shard decision is
   **64x4 / 16x4 >= 0.95** in each mode; the harness’s historical 0.90 threshold
   alone does not satisfy this design.
4. Gate generic 14 cells in `docs/exec1s/generic14.cells.txt`, plus **2s GET/SET
   p1/p32** in `docs/exec1s/2s-get-set.cells.txt`: union
   `h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,h47,h48,h49,h50,h63,h64`.
   POST/PRE and the same-binary null use unchanged gate offered-load plans and
   per-cell acceptance. Include the POST-layout/PAD-A layout comparison.
5. Record rate, cycles/op, instructions/op, IPC, latency, independent null,
   `atomic_txn_*`, WB sends, retired ops, client placement, IO/EX enters, owner
   passes, eager collapses and extra passes. For X3 use fused IO `iterations`
   as rotations. For X1 validate <=1.05 kernel entries per idle-EX rotation
   with a kernel-side count as well as counters. X4 requires holds >0 and
   sends/EXEC <=1.1 hot, <=1.05 uncontended, and remains owner-gated.

Reproduction, in order (correctness only):

```sh
taskset -c 48-63 python3 tools/exec1s_build.py
taskset -c 48-63 python3 tools/exec1s_trace.py
taskset -c 48-63 python3 tools/exec1s_retire_probes.py
taskset -c 48-63 python3 tools/exec1s_directed.py
taskset -c 48-63 python3 tools/exec1s_finish_proof.py
taskset -c 48-63 python3 tools/exec1s_live_receipts.py
```

After probe retirement, `tools/exec1s_trace.py --collect-only` verifies the
retained hash bindings and completed logs without retracing.

The decision is improvement outside the existing per-cell null with no ordinary
cell regression. Instruction and allocation counts explain behaviour; they do
not establish throughput, IPC or latency. No rate has been measured here.
