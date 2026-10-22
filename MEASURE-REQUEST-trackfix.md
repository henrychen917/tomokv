# Lane trackfix

## trackfix

Base: `a7dfb9d2332d4c4e9d8bca983e439ba4b2bbba7e`. **Partial result: CC4.4
is fixed; DIFF-TRK-1 is reproduced deterministically and remains unfixed. This
branch is not a green tracking fix or a complete merge candidate.**

Scope: DIFF-TRK-1 (delayed tracking invalidations) and CC4.4 (false notification
drop accounting). Correctness runs use CPUs 96–103 for TomoKV, 104 for the
Redis 7.4 oracle, 105–111 for clients, and ports 22800–22899. Builds use
`taskset -c 96-111 make -j16`. No performance measurements or push.

The bugs5 DIFF-TRK-1 report and tracing receipts were read, as were the full
CC4.4 entries in `round4-read/REGISTER.md` and `round4-read/cmd-complex.md`.

### DIFF-TRK-1 and the requested ordering restriction

The existing consumer has no causal token for the required atomic=0/read-local=0
case. `Op::read_cut` exists only while atomic tracking is active;
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
| PRE `trackfix_order` (corrected fixture v2) | 16 | 160 | 128 DIFF-TRK-1 failures; 32 BCAST controls pass |
| POST `trackfix_order` (v2 fixture) | 16 | 160 | 124 exact-frame failures, four arming failures; 32 BCAST controls pass |
| PRE `trackfix_accounting` | 16 | 160 | 160 CC4.4 counter failures, correct delivered frames |
| POST `trackfix_accounting` | 16 | 160 | 160 pass |

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
to establish its notification branch before the scheduled SET. Those fresh
whole-job reruns are pending; the four failed arms are not skipped or relabelled.

### CC4.4 implementation and cost boundary

`src/cmd/notify.inc` counts records that actually request a keyspace/keyevent
publication. A tracking-only batch finishes after its invalidations; it no
longer mistakes an empty pub/sub chain for reservation failure. On a real
reservation failure, mixed batches count only publication records, once per
record even when both pub/sub routes are enabled.

The new directed assertion independently checks one fired event, one delivered
invalidation, and zero drops; both protocols compare the entire frame with the
oracle. Redis has no `notify_events_dropped` counterpart, so that field is
asserted against actual delivery, not a fabricated Redis INFO field.

No locked layout, Op field, queue, thread, dispatch gate or GET/SET handler was
changed. With tracking and keyspace notifications disabled, no NotifyBatch is
created and this changed retirement code is unreachable: zero additional
default-path allocation, shared-line write or instruction. This is not a claim
that an already armed keyspace-notification path has zero extra work: it scans
the existing records to count publication routes. No throughput claim is made.

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
| `build/tomokv` | `03dcbf1789bb1b31dd857ef992232660520d3c1b13d6ba5dbc44dea22073904d` | 7,747,750 |
| `build/tomokv-PAD-A` | `915b31442dc322b1fee26d2975f9a414bf56c785a9414d846dadb56b82805144` | 7,747,750 |

**PAD type A, behaviour twin:** PRE objects plus 224 unreachable tail NOP bytes,
matching POST's aggregate text size. It preserves all PRE function addresses and
sizes, but does not reproduce each POST function's layout. Four strict PAD
residual groups are retained; a separate check proves all four moved rlfence
trampoline targets return to the identical instruction, including both symbol
aliases per body. GNU properties match. See `pad.json` and
`identity/pad-relocations.json`.

The linked identity tool reports 8,555/8,641 identical groups and **12/12 selected
GET/SET/MGET/MSET groups identical**. Every changed body has a reason and complete
strict instruction/encoding differences under `docs/trackfix/identity/`.
Only the two xshard object files differ; 50 reported linked residuals originate
solely in byte-identical objects. They remain reported, with their provenance.

Ten compile-only xshard budget trials re-derived both namespace budgets from
IPA growth (+19 instructions in each unit) and tested the derived value ±8.
They can reduce unlinked residuals; the final linked command selection already
matches PRE. Baseline budgets are retained, with all trials recorded, rather
than treating an identity score as a merit result.

`make -j16 all` and every production-unit target succeeded. All **39 targets**,
including `all` and `mdbqsbr-live-arms`, pass `make -q` in
`docs/trackfix/freshness.json`.

### Validation still collecting

The unchanged standard differential is running on both arms, engines and
geometries, including both atomic settings. Fresh climon seed-19 repeats and
whole tracking/climon/pushtear/notification gate jobs are also being retained.
The final row counts, every failure, and every NOT RUN item will be recorded
below when the processes finish. Early POST seed-19 runs still have duplicate
invalidations, as expected for the unresolved primary bug.

The first `gates_test.py` run completed 67 tests with seven scheduler-fixture
timeouts during concurrent compilation/checks; its original log is retained.
A quiet rerun is pending. No test deadline or expectation was relaxed.

### Maintainer merit request

Use the unchanged 14 cells in `docs/trackfix/generic14-cells.txt`, with the gate's
own quiet-box instrument: PRE/PRE null, PRE/POST, and PRE/PAD-A, identical affinity,
offered load, warmup, data, geometry and ABBA ordering. Report PRE and POST rate
at matched load, cycles/op, instructions/op, IPC, and the existing depth-one
latency score for every cell. The verdict is the existing no-regression rule,
not an instruction-count improvement. The PAD-A interpretation is limited to
aggregate text size.

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
