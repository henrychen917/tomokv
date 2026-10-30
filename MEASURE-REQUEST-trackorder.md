# CLIENT TRACKING flush reply order

## trackorder

Lane `cx-trackorder`, based on `e32b04a445b056976abb308aa598e356fcbaae74`.
No push. **NOT RUN: performance benchmarks, load generators and the full gate
iteration**, reserved for the maintainer by this lane's authorization.
Builds, instruction scopes and correctness processes use CPUs 0–15; default server geometry is
16 shards, split 6:2 or eight fused threads. The primary slot uses CPUs 0–7;
Tcl and differential jobs use CPUs 8–15 with ports 20120–20129 and 20140–20149,
respectively. Existing txnorder jobs retain their explicit four-owner 4:4 shape.
All listeners use
20100–20199 and every boot inherits `LC_ALL=C`.

### Oracle and change

The Redis 7.4.10 oracle distinguishes **SYNC/default** from **ASYNC**:
on a directly tracked RESP3 flushing connection, SYNC/default sends the null
invalidation before `+OK`; ASYNC sends `+OK` first. With an ECHO on each side,
the frames are respectively `before, invalidate(null), OK, after` and
`before, OK, invalidate(null), after`. BCAST, default, OPTIN/OPTOUT (both
remembering and nonremembering reads), and NOLOOP preserve that distinction.

The complete oracle/candidate streams are recorded as hexadecimal RESP frames,
per connection. The tested REDIRECT pairs are RESP2→RESP2 and RESP3→RESP3.
A RESP2 REDIRECT receiver gets a `message` on
`__redis__:invalidate` with a null bulk; RESP3 direct/REDIRECT receivers get a
two-element `invalidate` push with RESP3 null. Other tracked clients receive
one null invalidation, even with no remembered key or NOLOOP. Separate TCP
streams have no total byte order; receipts do not invent one by ordering reads
in the harness. PING fences check each recipient's subsequent stream.
`docs/trackorder/wire-examples.json` exposes representative oracle/PRE/POST
streams as escaped ASCII; the final archives retain every hexadecimal frame.

Production implementation lives in `src/cmd/tracking.cc`; `src/net/wb.h` adds
only a const accessor for its existing retirement pointer. A flush raised
during its recipient's own retirement can append at the established boundary
before reply assembly. The ROB publishes its cursor once per drain, so the
cold helper skips already-Free slots to find the actual retiring Op. SYNC and
default use this boundary; ASYNC, other recipients, and suppressed replies
retain ordinary OOB deferral. Suppressed replies have no `+OK` to precede, and
their push must remain outside reply segments that suppression discards.

There is no added per-thread, connection, shard or Op state. The helper has no
allocation, retry, seqlock or owner hand-off; all struct layouts are unchanged.
Non-flush invalidations do not call it. With tracking OFF this code is unreachable.

Porting to flushfix2/flushfix3: retain the existing completion-side call to
`climon_flush_completed` after **all** shard effects finish and before final
reply assembly, while the originating Op remains Done in its ROB. The fix
depends on that boundary, not the scatter kind or the implementation of
clearing stores. Both inspected branch tips retain this exact hook and ordering:
`cx-flushfix2` at `a396a42e5` and `cx-flushfix3` at `aa677139a`. The two-file
production diff therefore needs no scatter/atomic redesign. Re-run the row on
whichever combined design the owner selects. If FLUSH later moves to another retirement branch, move
that same cold hook with it. Do not emit at dispatch or before owner completion.

### Frozen arms

POST's production source is committed at `e1d632f94`; subsequent commits add
tests, receipt tooling and evidence without changing that production diff.

| Arm | File | SHA-256 |
|---|---|---|
| PRE (`e32b04a44`) | `build/tomokv-PRE` | `414d439e4cb6c86bb963a08747b82b1f314566ce6107bdaa718a40e3d9389b46` |
| POST | `build/tomokv-POST` | `8a8a8e98796570592b1e05ceb0bea98ceac8b9afbc1b4248092839bfdc1d5193` |
| PAD-A | `build/tomokv-PAD-A` | `380a1d0368acca59a636f6c9dd732881503276ab053ad1bc321e365c65d317fd` |

**PAD type A — behaviour twin:** POST with each namespace's cold
`tracking_flush_before_reply` entry forced to return false. This restores
PRE's deferral while retaining POST's exact text size, every section and
symbol address, and all other file bytes. Only two bytes differ in the
compiled binaries. Construction/verification: `tools/trackorder_pad.py` and
`docs/trackorder/pad.json`. Text sizes: PRE 8,729,431; POST/PAD-A 8,733,271.

Oracle: `/home/user/Projects/redis/src/redis-server`, SHA-256
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.

### Tracking OFF instruction proof

`tools/trackorder_counts.py` reuses the production command-scope fixture and
finite single-step tracer. All **80 paired cells have zero added instructions
and identical per-function counts**: GET/SET/INCR/MGET/MSET × batches 1/32 ×
1s/2s × atomic 0/1 × both database namespaces. Counts include executed NOPs in
the named TomoKV functions and exclude library callees/fixture glue. These are
serverless command scopes, not whole-operation or throughput measurements.

`docs/trackorder/counts/comparison.csv` contains every PRE/POST count; individual
JSON receipts retain the function attribution. The rebuilt headline used for
linking the probe has **byte-identical .text and .data** to delivered PRE;
the only .rodata differences are the two INFO git-SHA strings (14 bytes).
`headline-rebuild.json` records that check. The object comparison additionally
finds **1,587/1,587 hot bodies byte-identical**, including relocation targets
(`docs/trackorder/identity/objects.json`). No instruction budget was changed.

### Correctness receipts

`tools/trackorder_run.py` uses the gate's `GATE_ONLY_JOBS` interface with
`GATE_PROOF_NO_RATES=1`. Every invocation is partial; the `iteration` tier
invocations select only differential jobs and cannot enter ABBA or the full
gate tally. Existing optional battery rate assertions remain maintainer work.

The final directed job runs 864 cases per boot across 24 boots: both database
variants, modes, engines and atomic settings, plus fused read-local 0/1. Every
leg uses the gate's whole-job interface, records all cases after failures and
rejects a changed candidate binary.

| Frozen arm | Exact matches | Ordering failures | Legs |
|---|---:|---:|---:|
| PRE | 18,432 | 2,304 | 24 |
| POST | **20,736** | **0** | 24 |
| PAD-A | 18,432 | 2,304 | 24 |

Every PRE/PAD-A failure is independently checked as the directly tracked
flushing client's null push following its SYNC/default `+OK`; removing that
one push leaves every stream identical to the oracle. There are no unrelated
failures in the final matrix. This is a non-vacuous negative control in every
mode/engine/database/atomic/read-local leg. Full wire streams and shutdown
receipts are committed in `docs/trackorder/final/*-proof.tar.gz`, with readable
per-leg summaries alongside.

`python3 tests/gates_test.py` passes **76 tests**, including its nested 14-test
persistence self-test. All four build invocations covering `make all` and the
gate's entire production-unit target list returned zero. After the gate's own
production prerequisite job, all **59 `make -q` checks pass**, including each
production target, both live MDB arms' `all` targets and the cost fingerprint.
See `docs/trackorder/units/freshness-final.json`.

To stay within the disk budget, completed temporary count binaries/objects were
removed after their receipts and PRE text identity check. Debug sections of
auxiliary unit executables were compressed with `objcopy`; every allocated
section's bytes, address and size were independently verified unchanged. The
four main/merit binaries were excluded. Compression receipts retain before and
after hashes; initial aggregate freshness misses caused by the newer auxiliary
files were resolved by the gate's ordinary production-unit build. No source
flags, checks, assertions or EXPECT counts were altered for this.

The gate's registered `unit/tracking` Tcl subset passes in both modes:
**40 passed, 0 failed, 18 skipped per mode**, using the existing checked-in
skip policy unchanged. A supplemental unrestricted census (no skips) produces
**30 passed, 4 failed and an idle timeout per mode**, identically on POST and
PRE. The four failures concern undeclared script keys, multiple-key response
interleaving, transaction response interleaving, and eviction/lazyfree. Both
arms then time out at the tracking-table-key-eviction test. The remaining
unrestricted tests are **NOT RUN due to that timeout**; this is not a claim
that the full upstream tracking suite passes. Exact events, errors, server
logs and baseline controls are in `docs/trackorder/tcl/*-proof.tar.gz` and
`docs/trackorder/tcl-summary.json`.

The primary selected-job run passes **275 rows, 0 failures**. It includes the
tracking, keyspace, FLUSH, pub/sub, RESP3 and txnorder jobs; each matrix job
runs its own complete engine/mode legs. Whole-job receipts are in
`docs/trackorder/jobs/batteries-uring-proof.tar.gz`, with a per-job summary.
The ordinary-job epoll repeat passes **190 rows, 0 failures**, including both
atomic settings of split, armed fused and ordinary fused batteries, client
tracking/reply suppression, notifications and txnorder. Its whole-job archive
and summary are alongside the primary run. Differential and supplemental
verdicts are still being collected.

Earlier evidence remains separate: the first harness launch failed because
the TomoKV readiness-banner check was applied to Redis. The initial PRE
matrix then found 1,152 expected SYNC ordering failures plus two BCAST setup
events that raced the next registration. The final harness explicitly turns
tracking OFF and requires zero live trackers before the next seed. An
intermediate POST run crossed a binary rebuild and is exploratory only;
final acceptance uses immutable arm paths and verifies their hashes.

### Row accounting

One new row, `tracking FLUSH reply order vs Redis 7.4`, is collected at
`tests/gate.sh:6310`, before the quick-tier branch at line 6380 and its exit at line 6384.
**DQ=+1, DF=+1**. Maintainer-owned expectations should become **978/995** from
977/994. `EXPECT_QUICK` and `EXPECT_FULL` are unchanged. The explicit label
fixture contains all 995 source-declared labels with no missing/extra entries;
its count guard intentionally remains red against the owner's unchanged 994
(`docs/trackorder/label-fixture.log`).

### Maintainer merit request

Run the unchanged **14 generic cells** in
`docs/trackorder/generic14-cells.txt`, plus the **2s GET/SET p1/p32 null cells**
in `docs/trackorder/null-2s-cells.txt`, through the gate's own quiet-box ABBA
instrument. Arms: PRE/PRE null, PRE/POST, PRE/PAD-A. Use matched offered load,
warmup, dataset, affinity and geometry. Report rate, cycles/op,
instructions/op and IPC together, and the declared depth-one latency score.

Rate at matched load decides rate cells; the declared latency score decides
latency cells. Every main-command cell must show no reproducible regression
against the session's PRE/PRE control. The split GET/SET cells should remain
null; PAD-A is the exact-layout PRE-behavior control. Instruction counts alone
do not establish performance. **No throughput claim is made.**
