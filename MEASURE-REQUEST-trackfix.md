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
quick-tier exit at line 4457: **DQ=+2, DF=+2**. The owner must change 685/702 to
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

Ten compile-only xshard budget trials were performed for CC4-v1 and are retained
under `budget-trials-CC4-v1.json`. The final source already preserves all selected
linked command bodies with baseline budgets 128705/127713; no further budget
change is needed. Identity remains a proxy, and every residual goes to merit.

`make -j16 all` and every production-unit target succeeded. All **39 targets**,
including `all` and `mdbqsbr-live-arms`, pass `make -q` in
`docs/trackfix/freshness.json`.

### Validation still collecting

The unchanged standard differential is running as `PRE-final` and `POST-final`
on both engines and geometries, including both atomic settings. It retains the
standard permanent seeds, rotating seed 21, repeated MULTI legs, and split-mode
equivalence matrix. The final seed-19 POST cohort is also still running; actual
duplicate frame counts, including zeros, are in `control-counts.md/json`.

All new rows use `GATE_ONLY_JOBS` through `tests/gate.sh` with all declared legs.
Whole feature, clientfix, notification, netcmd-unit, metadata, debug, fused and
ring jobs are being rerun on the final binary. Earlier CC4-v1 whole-job results
were 173/173 epoll, 220/220 uring, both supplementary fused notification jobs
7/7, and ring units 3/3. They are retained but do not stand in for final reruns.

`python3 tests/gates_test.py` passed all **67 tests** on its quiet rerun, including
the nested 14-test persistence self-test. The first run's seven scheduler-fixture
timeouts during concurrent compilation/checks remain in `gates-test.log`.
No test deadline or expectation was relaxed.

An early auxiliary-listener deviation is retained explicitly: climon's Python
reader-control fixture used `bind(0)` before the confinement shim existed. Its
first PRE seed-19 runs and the early PRE standard runs are preliminary. The shim
confines Python fixture listeners to 22880–22898 and logs them in
`fixture-ports.log`; main server/oracle listeners use their assigned lane ports.
PRE runs 11–30 supply the 20 fresh, confined seed-19 controls. All four standard
PRE legs are being rerun from scratch with confinement as `PRE-final`.

### Maintainer merit request

Use the unchanged 14 cells in `docs/trackfix/generic14-cells.txt`, with the gate's
own quiet-box instrument: PRE/PRE null, PRE/POST, and PRE/PAD-A, identical affinity,
offered load, warmup, data, geometry and ABBA ordering. Report PRE and POST rate
at matched load, cycles/op, instructions/op, IPC, and the existing depth-one
latency score for every cell. The verdict is the existing no-regression rule,
not an instruction-count improvement. Final PAD-A matches POST's exact layout;
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
