## exec1s

Lane: `/home/user/Projects/cx-exec1s`, branch `cx-exec1s`, PRE `83e0b809d`.
This request is for the maintainer's quiet-box instrument. No throughput result is claimed.
Correctness work is pinned to CPUs 80–95, server geometry 80–87 / ratio 6:2 /
16 shards and clients 88–95, using ports 20100–20199. Builds use `-j16`.
Independent correctness jobs also use the reversed 88–95 server / 80–87
client assignment. The two sequences use ports 20100–20149 and 20150–20199;
their durations are not performance evidence.
Directed jobs retain their own explicit shape overrides, such as txnorder's
four-owner split boot and the 64-shard zero-copy rows.
No push. `EXPECT_QUICK` and `EXPECT_FULL` are unchanged.

Status: the initial Opus-max audit found an overlapping X2 write that races a
read-local reader and a statistics-publication omission. Both are repaired and the final production diff passed a focused Opus review.
The rebuilt POST passed all 48 ordinary-command instruction scopes. Rebuilding
and re-proving the other affected arms and the live jobs is in progress. The receipts
below still describe the pre-audit images until replaced. They are retained under
`build/exec1s-evidence/pre-opus-repair/`; missing proof is not a pass.

### Arms and changes

| Arm | Cumulative change | Shared path |
| --- | --- | --- |
| PRE | Exact baseline `83e0b809d` | Both modes |
| X0 | Per-thread client peaks/live counts, IO/EX enters and waits, owner passes; DEBUG-only MVCC visits | Reporting only |
| X1 | Issuer-local registered ring fds; enter fused EX ring for SQEs, owed CQEs, incoming deferred task work or retained CQ overflow | Fused rings; common ring CQE plumbing |
| X2 | Reclaim decided prefixes at eight live records after completed MULTI tasks; O(1) no-group blind-scan exit; reuse command hashes; retain changed-field statistics publication | Both modes |
| X3 | At most two additional full owner passes per rotation, selected by per-thread runnable hints | Fused only |
| X4 | Separate `TOMO_EXEC1S_WB` arm, based on X3; hold a block's ready prefix while its EXEC is in flight | Both modes; excluded from default POST |
| X5 / POST-release | X3 plus participant-sized EXEC arrays and queued spec-id classification | Both modes |
| POST-layout / PAD-A | Exact common-image behaviour-twin control pair | See PAD semantics below |

The FIFO lane is absent. No connection shedding, batching, co-location,
pipelined EXECs, or latency-tracking changes were added. The inherited
LAT-OFF-EXEC-1 cost is present in PRE and every candidate.

X1 retains the fused pass's clock read. Deferred owner work and housekeeping can
precede the batch re-cut, so removing it did not meet the design's clock proof.
Registered-fd guards unregister on their issuer before post-join ring teardown.
Outgoing message, AOF and snapshot completions are counted when queued and
accounted exactly once when first reaped, including filtered/deferred CQEs.
The incoming-message fixture exposed a missing case: an EX ring may have no
owned SQE while a peer's MSG_RING completion remains deferred. Fused EX rings
now request TASKRUN_FLAG, inspect the kernel task-work/overflow bits, and service
them even when no owner task progressed. The older-kernel setup fallback removes
DEFER_TASKRUN as well. This follows the documented
[task-run flag contract](https://man7.org/linux/man-pages/man2/io_uring_setup.2.html).
Directed checks require an actual incoming-only window and a retained overflow
window. Removing incoming service in a throwaway binary fails the unchanged
exact-CQE assertion. This kernel keeps TASKRUN set during the tested overflow
backlog, so removing only the overflow bit is not independently discriminated.
The entry counters count submit/get-events requests; waits are separate because
liburing can satisfy a wait without a syscall. Do not silently equate their sum
with a kernel trace's syscall count.

X2 loads the completed commit cutoff before the reader floor and uses the
existing cleanup and QSBR retirement helpers. The one-byte group count consumes
existing AtomicPendingState padding, without changing any locked footprint. It
is modulo 256; the fast exit additionally requires fewer than 256 total live
records. A two-byte install-flag/count update has explicit endian/offset locks
and excludes the adjacent immutable reader discriminator. A TSAN witness must
pass on that helper and reject the old four-byte write; a real 256-group fixture
checks that wrapping cannot incorrectly select the no-group fast exit. Ordinary
reclamation then checks every count from 255 to zero before sidecar destruction.
These directed decrements exercise the aborted slow-collapse path; the other
collapse paths share the same decrement helper and were inspected in the audit.
A pinned floor may retain more than eight records; that is required correctness,
not an exemption from the floor. No read retries or seqlocks were introduced.

X3 hints contain no shard/client pointer or per-shard ownership structure. A
stale hint after a move only schedules a guarded normal pass; normal polling
remains the liveness backstop. The pass retains the existing freeze, snapshot,
read-local publication and cross-shard commit guards. RetrySoon also rings the
hint: it is a service opportunity, not proof that a remote hand-off completed.
The final linked production idle-rotation scope measured **+30 instructions in
normal and +16 in db0**, failing the design's <=+2 target. Earlier pre-regeneration
links measured +16 in both namespaces. The final receipt uses the matching X2/X3
images in the manifest. This is an explicit acceptance miss, not a claim of a
harmless cost or of a rate change.

The initial audit also found that testing only key count before calling
`publish_size()` omitted changed expiry/object-byte statistics on retry passes.
The call is restored; its existing implementation already avoids unchanged
producer stores. A directed task outside a batch checks the same-key-count case.

REGISTER had no `exec1s D5` owner line when X4 was reached. No free Op bit exists
in this base. The isolated arm uses an exact ROB-generation interval in the
existing MultiSession heap object, avoiding a footprint change or a new reset
instruction on ordinary commands. Interactive MULTI has no buffered EXEC and
therefore does not qualify. No D4 barrier was removed.

X5 touched about 35 production array-access sites in multi.inc and txn_key_queue.inc,
below the design's approximately 60-site stop rule; Shard did not change. A
one-byte-per-shard map indexes participant-sized arrays. At 256 participants,
slot 255 becomes valid only after every physical shard has a slot. WATCH-only
and disconnect cleanup states keep their cold identity indexing. Existing
synthetic phase fixtures explicitly initialize identity-indexed storage before
installing their artificial claims; their assertions are unchanged.

Final release images and cumulative source commits are listed in
`docs/exec1s/arms.json` and `docs/exec1s/SHA256SUMS`. X5 and POST-release are
byte-identical. PRE retains its original frozen binary; the separately linked
baseline object tree differs only in DWARF/build ID. Every allocated code/data
section and relocation table, plus addresses and NOBITS sizes, matches exactly
(`docs/exec1s/pre-link-equivalence.json`). Command probes and PAD use that proven
equivalent baseline object tree.

### Correctness and instruction receipts

Evidence directory: `build/exec1s-evidence/`. Reproduction driver:
`taskset -c 80-95 python3 tools/exec1s_proof.py --families --self-test`.
The driver selects individual gate jobs; it does not run the full iteration or
ABBA. `GATE_PROOF_NO_RATES=1` uses the gate's existing partial-proof path:
the embedded atomic_ryow throughput comparison is NOT RUN under this lane's
no-performance authorization, while its correctness schedules remain enabled.
`flip_saturated` and `atomic_floor` invoke memtier and are also NOT RUN here;
the driver excludes them and rejects explicit selection. They remain required
maintainer jobs. The diagnostic run was stopped before either job began.
`--differ-arms PRE,X0,X1,X2,X3,X4,POST-release,POST-layout,PAD-A --engines uring,epoll`
selects standard-seed differential jobs with every internal mode/atomic leg.
Each gate's own artifacts, ledgers, logs and exit status are retained.
The complete oracle source root is `/home/user/Projects/redis`, Redis 7.4.10,
commit `f103d127`. Its binary, the `/home/user/Projects/redis74` binary-only copy
and the historical gate path are byte-identical, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`
(`docs/exec1s/oracle.json`).

The command scope uses linked production owner/scatter routines, both physical
namespaces, 1s/2s, batches 1/32, GET/SET/INCR/MGET/MSET; MSET additionally uses
atomic 0/1. There are 48 cases per arm. It counts named Tomo instructions,
including inlined code, between the fixture's scope markers. External library
callees and fixture glue are excluded, clocks are deterministic, and exact data
assertions must pass. It does not count the surrounding network rotation or WB.

Superseded pre-audit command-count proof: **PASS**, all 48 cases for each of X0, X1, X2, X3,
X4, POST-release/X5, POST-layout and PAD-A; every arm's maximum delta is zero.
`docs/exec1s/command-counts.json` binds every case to its probe hash and every arm
to its production hash. The complete 432-case run and build receipts are in
`build/exec1s-evidence/instructions/`. Initial X2/X3/X4 links added 496
instructions on atomic MSET batch 32; those failed receipts remain archived.
The final links include the repaired inline publication and link helpers.
X5 also restores the ordinary-command inlining boundary with the existing
xshard translation-unit budgets: normal 148,537 → 149,306 and db0 147,343 →
148,100. The boundary trials are retained in `docs/exec1s/budgets/`; these are
compiler controls, not evidence of a throughput improvement.

Superseded pre-audit receipts: `python3 tests/gates_test.py` **PASS**, all 73 tests on a stable tree
(`build/exec1s-evidence/gates-test-stable-tree.log`). Reorder generation and its
stale-copy control pass; the gate's strict identity job passes 322/322 bodies
and all missing-body/opcode negative controls (`POST-reorder-final.json`).
All 50 required freshness checks pass (`docs/exec1s/freshness.json`), including
all production-unit targets, the underlying two database-QSBR control builds,
and the candidate-bound blocking-cost fixture. Release, ASAN and read-local
debug build jobs pass (`POST-instrument-builds.json`).

The final complete selected-family run, supplementary fused legs, AOF CQ
observations, X4 hold/control witnesses, and standard differentials for every
unique image on both engines are still in progress. X5 and POST-release share
one differential receipt because they are byte-identical. Historical X0 uring
differential results are superseded by the final regenerated image. Earlier
watchdog failures under concurrent compilation/tracing and the gate self-test
run that overlapped a history rewrite are retained; no timeout, seed, assertion
or expected row count was relaxed.

X6 adds four scored rows, one for each 1s/2s × atomic 0/1 combination. Its literal
`collect_job exec1s` is at line 5695, before the quick-tier exit at line 5803: **DQ=+4, DF=+4**. The base
already carries execindex's two uncounted rows (800/817 required versus stored
798/815). With exec1s the expected totals are **804 quick / 821 full**, subject
to the owner's integration inventory. The lane does not edit either constant.

X5 allocation receipt (`docs/exec1s/allocation-comparison.json`): the same
`allocate_state` through `prepare_commands` scope, two actual Local INCRs and two
physical shard participants, counts all C++ allocation requests in that scope.
Both namespaces use the eight-thread topology. POST uses 4,315 bytes at 16 shards
and 4,490 at 64; PRE uses 13,514 at 64. The geometry ratio is 1.041
(PASS <=1.2). POST/PRE is 0.332 (**FAIL <=0.25**).
The separate initial-state allocation count is not substituted for this complete
scope: POST defers its participant allocations until discovery. No rate follows
from these byte counts.

| Serverless scope | PRE / preceding arm | POST / candidate | Verdict |
| --- | ---: | ---: | --- |
| Idle fused rotation, normal (X2 → X3), instructions | 3,665 | 3,695 | FAIL: +30, target <=+2 |
| Idle fused rotation, db0 (X2 → X3), instructions | 3,631 | 3,647 | FAIL: +16, target <=+2 |
| EXEC preparation/dispatch, normal 1s, instructions | 11,176 | 6,930 | Below PRE |
| EXEC preparation/dispatch, normal 2s, instructions | 8,776 | 6,930 | Below PRE |
| EXEC preparation/dispatch, db0 1s, instructions | 9,992 | 5,846 | Below PRE |
| EXEC preparation/dispatch, db0 2s, instructions | 7,592 | 5,846 | Below PRE |
| Complete allocation scope, 1s / 64 shards, bytes | 13,514 | 4,490 | FAIL: 0.332×, target <=0.25× |
| POST allocation geometry, 2s / 16 → 1s / 64, bytes | 4,315 | 4,490 | PASS: 1.041×, target <=1.2× |

The allocation values apply to both namespaces. IO instructions exclude queueing
and library callees, as specified in `docs/exec1s/io-counts.json`; the scope is
identical for PRE and POST. Rates, IPC and latency remain unmeasured.

The first complete live debug attempt caught an X5 preparation crash: registry
metadata for lowered option-bearing commands can name claim-only shards outside
the exact execution task set. The compact map now allocates those claim slots
without adding tasks or changing barriers. A directed LMPOP fixture covers the
case and the original live execfix reproduction passes on the corrected code.
The failed image and receipts remain under `build/exec1s/v1-claim-crash`.
A later breadth run found missing regeneration of R7 loop envelopes and two
serverless initialization failures in X1. Every affected lever now regenerates
its R7 envelope; X3's extra R7 turns call the guarded R7 owner pass. Ring service
checks require an initialized ring, and registration tolerates the fixture's
absent executor. The strict off-path inventory explicitly replaces each
runtime's four sweep clones with its full sweep body and includes X3's new
ordinary owner-turn body; byte comparisons and negative controls remain strict.
The diagnostic image `7818c120dbe9...` and failed rows are preserved.

Ring counters now occupy separate cache lines per issuer; earlier arm images
with adjacent issuers sharing a counter line are superseded. Final builds and
proof must use the updated arm manifest, not those historical images.
The preservation audit is in `docs/exec1s/rules.md`. The design's separate
Opus-max critical-path/struct audit completed through the local Claude CLI
(`claude-opus-5-5`, maximum effort, read tools only). The complete initial report
and provenance are `docs/exec1s/opus-audit-initial.{md,json}`. The amended X6 head
changed only docs/proof tooling, resolving its tree-identity caveat. A focused
follow-up accepted the repairs, and a final bounded review approved the owner-word
construction and outlined MULTI completion helper. Reports and provenance are
`docs/exec1s/opus-audit-followup.{md,json}` and `opus-audit-final.{md,json}`.
The last audit used a stale fixture hunk and incorrectly stated that no existing
regression-test friend existed; compilation caught the duplicate. The corrected
fixture uses that friend’s existing accessor. Production was unchanged, and all
twelve corrected directed checks passed. The family run was intentionally stopped
at source repair; the unchanged PRE io_uring differential and execfair run passed
(`PRE-differ-uring-attempt-2.json`).

### Maintainer merit request

Use each arm's own PRE, identical arm options, matched offered load and the
gate's existing ABBA/null rules. Report per cell: rate, cycles/op, instructions/op,
IPC, latency and the existing independent holdout/null result. Do not average
away a failing cell. The serverless count proof is complementary to rate.

1. `/home/user/Projects/calib/exec-merit.py`: 16, 32, 64 and 128 connections,
   pipeline 4, hot and uncontended, atomic 0/1 in **1s** for every arm. Run **2s**
   for shared changes X2, isolated X4 and X5, plus their preceding arms and PRE.
   Use three blocks. `--conns` accepts one integer, so use four invocations.
   The 1s cell names are `x1s_a0_unc,x1s_a0_hot,x1s_a1_unc,x1s_a1_hot`;
   the shared-path 2s cells use the corresponding `x2s_` prefix.
   Preserve the merit harness's four plain INCR clients in hot cells, its
   placement, read-local setting, and databases=1. Include Redis **7.4.10** as
   the owner-specified reference and record its binary digest and IO-thread
   grammar. Compare each Tomo arm to its own baseline, independently of Redis.
2. `/home/user/Projects/calib/exec-depth-sweep.py` in both modes, atomic 0/1,
   cross-owner / same-owner / same-shard placements and depths 16x1,16x4,32x4,
   64x4,128x4. The X2 same-shard target is **64x4 / 16x4 >= 0.95** in each mode;
   the harness's historical 0.90 criterion alone does not satisfy this design.
3. Gate ABBA unchanged generic 14 cells, copied in
   `docs/exec1s/generic14.cells.txt`: h01,h02,h15,h16,h17,h18,h31,h32,h33,h34,
   h47,h48,h63,h64. Include **2s GET/SET p1/p32** explicitly: h17,h18,h49,h50,
   copied in `docs/exec1s/2s-get-set.cells.txt` (16 unique cells in the union).
   Keep 1s cells in the request. Use the gate's accepted per-cell null
   resolution and unchanged offered-load plans.
4. Collect X0 per-thread client placement and ring-enter/pass counts. For X1,
   validate an otherwise idle EX ring gives at most 1.05 total kernel entries
   per fused rotation using a kernel-side count as well as the counters. For X3,
   use the fused IO thread's `iterations` as rotations: `owner_passes` includes
   the added passes and is not a rotation denominator. Record extra owner passes
   and owner rotations per EXEC. For X2, use a DEBUG observation build for
   records visited per EXEC at 16x4 versus 64x4; target
   ratio <=1.5, with eager_collapses >0. These debug observations are not release
   rate arms.
5. X4 only: report WB sends per EXEC (hot <=1.1; uncontended <=1.05) and holds >0
   in both modes. D5 remains an owner decision; a passing rate does not authorize
   inclusion in default POST.
6. X5: report allocation scope and bytes alongside its participant count; the
   design asks 64-shard 1s <=1.2× 16-shard 2s and <=0.25× PRE. Retain the IO-path
   instruction receipt from multi_handle_io through multi_dispatch_attempt.

Primary performance verdict: improvements must survive the gate's existing
per-cell null, with no regression in ordinary cells. The owner's target remains
hot EXEC at least Redis 7.4.10 in both modes. This lane makes no assertion that
these refinements reach it.

### PAD semantics

**PAD-A is type A, a behaviour twin:** PRE behaviour with the candidate's exact
common text/data layout. `tools/exec1s_pad.py` links the production candidate
first and symbol-isolated PRE objects second. POST-layout enters the candidate;
PAD-A differs only by a five-byte main-entry jump into PRE. ELF sections, symbols
and function addresses must match. Measure POST-layout versus PAD-A to control
that common layout, and PRE versus POST-release separately for the ordinary
release candidate. This control is explicitly not an exact-size twin of the
smaller standalone release ELF. The generated receipt records both hashes,
patch bytes, pre-object hashes and the limitation.


## exec1s-c

Continuation on branch `cx-exec1s-c` from `bd90f09de`. All earlier runtime,
instruction and binary receipts are VOID; their replacement is in progress.
The source audits remain historical design context, not current proof.
Builds and correctness work use CPUs 48–63 only, `-j16`, servers 48–55 and
clients 56–63, ports 20400–20499. No performance workload or full iteration
is authorized in this lane. X4 remains excluded from POST: REGISTER has no
`exec1s D5` owner line. The final merit request is 64 connections in both modes,
POST/PRE three blocks, per-lever attribution one block, POST depth sweeps in
both modes, and the generic cells plus the 2s GET/SET p1/p32 null.
