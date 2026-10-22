# Lane trackfix

## trackfix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. **Partial result: CC4.4
is fixed; DIFF-TRK-1 is reproduced deterministically and remains unfixed. This
branch is not a green tracking fix or a complete merge candidate.**

Scope: DIFF-TRK-1 (delayed tracking invalidations) and CC4.4 (false notification
drop accounting). Final correctness receipts use CPUs 96–103 for TomoKV, 104
for Redis, 105–111 for clients, and listening ports 22800–22899. Builds use
`taskset -c 96-111 make -j16`. See the early auxiliary-listener deviation below.
No performance measurements or push.

The bugs5 DIFF-TRK-1 report and tracing receipts were read, as were the full
CC4.4 entries in `round4-read/REGISTER.md` and `round4-read/cmd-complex.md`.

### DIFF-TRK-1 and the requested ordering restriction

The task requires ordering information “already carried by the write and the
read.” The existing consumer has no causal token for atomic=0/read-local=0.
`Op::read_cut` exists only while atomic tracking is active;
`NotifyRecordImpl::sequence` is local to a batch, and TrackingInvalidate carries
only the key and writer ID. [The information proof](docs/trackfix/ordering-constraint.md)
constructs two indistinguishable consumer states that require different answers.
The pending read's Done state proves completion, not its order against a foreign
write. Erasing the pending entry would also discard required protection.

An asynchronous clarification asks whether adding ordering metadata confined to
armed tracking reads/notifications is allowed, keeping unarmed command bodies
unchanged. It is unanswered. No causal deduplication patch has been installed.
The remaining work includes the overlapping/newer-write retirement fix and its
directed non-loss controls; these are **NOT RUN/NOT IMPLEMENTED**, pending that
constraint resolution. No successful POST DIFF-TRK-1 proof is claimed.

`tools/trackfix_schedule.py` makes a disposable copy of tracking.cc, retaining the
selected arm's other objects and link order. It delays a real older SET transport
event, then calls the unchanged consumer while GET is Done, its pending entry
still exists, and its tracking retirement has not happened. The test next retires
the GET and executes DEL. The hook changes scheduling only and is absent from
PRE, POST, and PAD-A production binaries. Every held/replayed receipt must exist;
missing windows fail rather than skip.

| Own gate job | Server boots | Exact protocol/option cases | Result |
|---|---:|---:|---|
| PRE `trackfix_order`, final fixture | 16 | 160 | 128 exact-frame failures; 32 BCAST controls pass |
| Final POST `trackfix_order` | 16 | 160 | 128 exact-frame failures; 32 BCAST controls pass |
| PRE `trackfix_accounting` | 16 | 160 | 160 CC4.4 counter failures, correct delivered frames |
| Final POST `trackfix_accounting` | 16 | 160 | 160 pass |
| PAD-A `trackfix_accounting` | 16 | 160 | 160 PRE counter failures restored, correct delivered frames |

Each product is 1s/2s × epoll/uring × atomic 0/1 × read-local 0/1, with RESP2
redirect and RESP3 default/BCAST/OPTIN/OPTOUT/NOLOOP cases. Redis 7.4.10 runs on
104. Its exact frame bytes and the target bytes are retained in each job's
`rows/` receipts. For remembering modes Redis sends no frame for the older SET
and one for the later DEL; PRE and this accounting-only POST send one at each
stage. BCAST correctly observes both changes and has no pending-read enrollment.

The first scheduling fixture tried to inspect argv at retirement; those bytes
are no longer a valid lifetime witness there. Its 128 missing-replay failures
are retained as `pre-order`, not counted as reproductions. v2 uses the actual
owned pending-read key and asserts both the Op pointer and Done state. PRE
opened 128 windows; POST opened 124 and rejected four missing notification
windows. v3 additionally arms an unmatched BCAST observer on the writer itself
to establish its notification branch before the scheduled SET. Fresh whole-job
reruns opened all 128 required windows on PRE and final POST. No failed window
was skipped or relabelled. Final receipts are
`docs/trackfix/proof/pre-newrows-final/rows/`,
`docs/trackfix/proof/post-v2-newrows-final/rows/`, and
`docs/trackfix/proof/pad-a-accounting/rows/`.

### CC4.4 implementation and cost boundary

`src/cmd/notify.inc` changes only the no-chain accounting branch. It counts
records that actually request a keyspace/keyevent publication, and increments
the dropped counter only for a nonzero count. A tracking-only batch therefore
adds no false drops. Mixed batches count publication records once even when
both pub/sub routes are enabled. Allocation-failure handling outside this
empty/reservation-failed chain branch is unchanged.

The new directed assertion independently checks one fired event, one delivered
invalidation, and zero drops; both protocols compare the entire frame with the
oracle. Redis has no `notify_events_dropped` counterpart, so that field is
asserted against actual delivery, not a fabricated Redis INFO field.

No locked layout, Op field, queue, thread, dispatch gate or GET/SET handler was
changed. With tracking and keyspace notifications disabled, no NotifyBatch is
created and the changed code is unreachable: zero additional default-path
allocation, shared-line write or instruction. Successful keyspace publication
also bypasses the new count: added work is confined to the existing no-chain
branch. The selected command bodies and all other defining object files except
the two xshard units match PRE. This is a source/identity proof of the cost
boundary, not a throughput or cycles claim.

The first accounting revision scanned every batch before publication. It was
replaced to remove that work from successful publication. Its binary and all
receipts are retained as the earlier CC4-v1 revision, not final acceptance.

### Gate inventory

Two new rows are collected at `tests/gate.sh` lines 4389–4390, **before** the
quick-tier branch at 4457 and exit at 4461: **DQ=+2, DF=+2**. The owner must change 685/702 to
**687/704** if both rows are retained. `EXPECT_QUICK` and `EXPECT_FULL` are
unchanged. The explicit label fixture contains exactly the source's 704 labels,
including multiplicities. Its count guard intentionally fails against the
owner's unchanged EXPECT_FULL=702; no missing or extra label exists. Receipt:
`docs/trackfix/label-fixture.json`.

### Binary and identity receipts

| Arm | SHA-256 | .text bytes |
|---|---|---:|
| `build/tomokv-PRE` | `da4431ffb8c7894c4048210b3197cedc137a35dfd21a0b5ff211a2bb3675fc26` | 7,747,526 |
| `build/tomokv` | `d8cd3f506e17b60ae619eed6b3732a3fc967abb8ec4b2dc982e1e7a2734d750c` | 7,747,478 |
| `build/tomokv-PAD-A` | `dc3df705455f1bf07011e00d5e8b516e6089c1df33fee4eb34751646f44b9337` | 7,747,478 |

**PAD type A, behaviour twin:** final POST with its two count predicates changed
from AND 3 to OR 3, one in each namespace. Every record then counts, restoring
PRE's `batch->total` behavior on this branch. All other file bytes, function
addresses, section sizes and symbol records are identical to POST. The whole
accounting job proves that all 160 PRE counter failures return. See `pad.py`,
`pad.json`, and `identity/pad-layout.json`. This is the final PAD-A; the earlier
224-byte tail-padding construction belongs only to CC4-v1. Final text shrinks
48 bytes, so no inverse-control PAD-B is requested.

The linked identity tool reports 8,623/8,641 identical groups and **12/12 selected
GET/SET/MGET/MSET groups identical**. Every changed body has a reason and complete
strict instruction/encoding differences under `docs/trackfix/identity/`.
Only the two xshard object files differ; one reported linked residual originates
solely in a byte-identical object. All 18 residuals remain reported with reasons.
The four generic multi-key dispatchers differ only in compiler switch-table
labels: an independent check verifies all instructions, encodings and complete
referenced table bytes. It also verifies all 18 CQE jump-table destinations
relative to their function. These checks explain residuals without removing
them from the strict identity result (`identity/literal-controls.json`).

Ten compile-only xshard budget trials were performed for CC4-v1 and are retained
under `budget-trials-CC4-v1.json`. The final source already preserves all selected
linked command bodies with baseline budgets 128705/127713; no further budget
change is needed. Identity remains a proxy, and every residual goes to merit.

`make -j16 all` and every production-unit target succeeded. All **39 targets**,
including `all` and `mdbqsbr-live-arms`, pass `make -q` in
`docs/trackfix/freshness.json`.

### Final validation

The unchanged standard differential completed as `PRE-final` and `POST-final`
on both engines and geometries, including both atomic settings. It retained
permanent seeds 7/19/20/23, rotating seed 21, repeated MULTI legs, and the full
32-combination split-mode equivalence matrix.

| Engine / geometry | PRE pass / fail | Final POST pass / fail |
|---|---:|---:|
| epoll / split | 475 / 0 | 475 / 0 |
| uring / split | 475 / 0 | 475 / 0 |
| epoll / armed fused | 464 / 2 | 463 / 3 |
| uring / armed fused | 466 / 0 | 466 / 0 |

Every failed standard leg is climon, and every mismatch is exactly two identical
target invalidation frames versus one oracle frame. PRE failures: atomic 1,
seeds 19 and 20 (six extra frames). Final POST failures: atomic 0, seeds 7 and 21;
atomic 1, seed 23 (ten extra frames). The exact bytes are in
`docs/trackfix/standard-failures.json`; complete transcripts, coverage artifacts,
seed plans and boot logs are archived under `docs/trackfix/differ/`.

The final seed-19 POST cohort completed all 20 fresh runs:
seven runs contain 14 duplicate frames. The 20 confined PRE controls have 14
duplicates in ten runs. Every per-run count, including zeros, is in
`control-counts.md/json`. **The required zero-duplicate POST result is not met.**
These are concurrent correctness runs, not estimates of comparative failure
probability or performance. All duplicate counts were checked against actual
two-identical-frame target bytes and one-frame oracle bytes.

All new rows use `GATE_ONLY_JOBS` through `tests/gate.sh` with all declared legs.
Final whole-job results:

| Job set | Pass / fail |
|---|---:|
| epoll: feature split/armed atomic 0/1, clientfix, notify, fused 0/1 | 173 / 0 |
| uring: same, plus netcmd units, notify order/AOF, metadata, debug 0/1, ring unit | 223 / 0 |
| supplementary fused `notify`, epoll | 7 / 0 |
| supplementary fused `notify`, uring | 7 / 0 |

These are whole-job partial ledgers, not a full-gate receipt. The new primary
tracking-order row remains red as recorded above. Earlier CC4-v1 results are
retained under their separate run names; all final rows name the final binary's
SHA in `command.json`. Canonical results and raw job logs are in
`docs/trackfix/gate-results.json` and `docs/trackfix/proof/`.

`python3 tests/gates_test.py` passed all **67 tests** on its quiet rerun, including
the nested 14-test persistence self-test. The first run's seven scheduler-fixture
timeouts during concurrent compilation/checks remain in `gates-test.log`.
No test deadline or expectation was relaxed.

The tracking assertion sweep and job mapping are in
`docs/trackfix/tracking-coverage.md`; the unchanged source-input proof is
`source-proof.json`. `replyschema.py` has no gate job, so its unchanged standalone
census ran on 16 fresh PRE/POST × mode × engine × atomic boots. Each covers
423 canonical invocations in RESP2 and RESP3. Tracking endpoints have zero
mismatches. Each boot still reports the same 17 non-tracking mismatches: stale
MOVE/SWAPDB inventory/case expectations, BGSAVE SCHEDULE, replication stubs,
ACL DRYRUN, LATENCY HISTOGRAM, and MEMORY STATS schema additions. Logs are kept;
no assertion was changed and this census is not labelled green.

`climon_128.py` is **NOT RUN**: it needs two live IO owners separated by 64,
which the required eight-server-CPU topology cannot provide, and has no gate
job. Its registered 128-owner mask arithmetic and negative-control job ran.

An early auxiliary-listener deviation is retained explicitly: climon's Python
reader-control fixture used `bind(0)` before the confinement shim existed. Its
first PRE seed-19 runs and the early PRE standard runs are preliminary. The shim
confines Python fixture listeners to 22880–22898 and logs them in
`fixture-ports.log`; main server/oracle listeners use their assigned lane ports.
PRE runs 11–30 supply the 20 fresh, confined seed-19 controls. All four standard
PRE legs were rerun from scratch with confinement as `PRE-final`. Earlier
failures remain preserved, including the invalid first fixture, the four v2
arming failures, the initial explicit build-only-job selection rejection, and
the first supplemental fused notification boot's split-only ratio error. Their
corrected whole-job runs are distinct receipts, never overwritten passes.

No lane listener or owned TomoKV process remains (`docs/trackfix/cleanup.json`).
The oracle executable SHA-256 is
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.

### Maintainer merit request

Use the unchanged 14 cells in `docs/trackfix/generic14-cells.txt`, with the gate's
own quiet-box instrument: PRE/PRE null, PRE/POST, and PRE/PAD-A, identical affinity,
offered load, warmup, data, geometry and ABBA ordering. Report PRE and POST rate
at matched load, cycles/op, instructions/op, IPC, and the existing depth-one
latency score for every cell. Use 96–103 for eight-server-core cells, 96–99 for
four-core cells, and 105–111 for clients. Rate at matched offered load decides
rate cells; the declared latency score decides depth-one latency cells. Every
main-command cell must show no reproducible regression against the PRE/PRE
control; instruction count alone cannot accept a change. Final PAD-A matches POST's exact layout;
a real effect should move POST while the PRE-behavior PAD-A remains flat.

The generic ABBA workload schema/driver has no CLIENT TRACKING setup option.
A tracking-enabled extra cell is therefore **NOT RUN / unsupported by that
instrument as shipped**. `tests/clientfix_widths.py` has a separate tracking
latency probe, but is not the requested generic ABBA instrument and was not run.
If the maintainer supplies tracking setup in that instrument, add a `d8s_l1`
twin with a held RESP3 tracker using `BCAST PREFIX never:` to arm collection
without matching workload keys; record the fired/dropped counters as well.

Full `tests/gate.sh iteration`, performance load generators and throughput
measurements are **NOT RUN**, reserved for the maintainer. The still-failing
DIFF-TRK-1 row prevents treating any merit result as complete task acceptance.
