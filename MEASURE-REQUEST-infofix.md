## infofix

Branch `cx-infofix`, PRE `393d6ceb129d8c99dffd70959d6a19267c525fe0`.
Production implementation is through `dbb355c55`; subsequent commits contain
batteries and evidence. No push. This is a partial compatibility result, not a
claim that all eight roots or the full Tcl job are green.

### Root dispositions

| Root | Result | Evidence / remaining boundary |
|---|---|---|
| INFO-MISSING-FIELDS | Implemented | CPU section in default/all/explicit selection; six real CPU counters; own git SHA, dirty bit, and 64-bit hexadecimal build identity. Directed oracle + 8 candidate legs pass. |
| COMMAND-DOCS-INCOMPLETE | Registered-command fix; Tcl closure blocked | Metadata-generated arguments, nested blocks/oneof, flags, history, and subcommands match Redis in RESP2/RESP3. The promoted CLI test still requires MIGRATE, absent from TomoKV's registry. |
| SLOWLOG-MAXLEN-PER-THREAD | Semantics implemented; concurrency review open | One lazy global ring; global cap and descending publication IDs; disabled logging retains history; subsequent armed completion trims it; discarded entries cannot return after growing the cap. Armed completion can wait on the shared ring mutex; see below. |
| DEBUG-LOADAOF-AOF-OFF | Implemented | Offline rewrite/reload works while appendonly remains no; absent AOF flushes keys and returns Redis's exact error. Enabled writers still drain before reload. |
| LAT-HIST-2 | Candidate; performance verdict pending | Homogeneous GET batches share metadata resolution and one histogram lock. Individual command timers and recording before completion publication remain exact. No averaging of outliers. |
| INFO-ERRORSTATS | STOPPED: architecture boundary | Exact accounting needs an accepted-attempt error journal. A generic error formatter hook counts discarded/replayed script attempts and cannot distinguish rejected from failed calls correctly. The exploratory hook was removed. |
| INFO-CMDSTAT-FIELDS | STOPPED: deliberate restriction | The root report and renderer explicitly omit unmeasured timing and unimplemented failed_calls. Always-on exact usec requires timing successful commands, conflicting with the zero-added-instructions requirement. |
| DEBUG-RELOAD-OPTIONS | STOPPED: architecture boundary | The assigned Tcl assertions persist/merge function libraries. Native snapshot plans contain keys/database mapping, with no function-library persistence. An option parser alone would not implement those semantics. |

The source boundaries are recorded in `docs/infofix/stopped-roots.md`.

Owner decisions: whether to extend accepted-attempt error accounting, permit
always-on command timing, persist function libraries, and expose/implement the
missing MIGRATE command. Those roots' unresolved named skips are retained;
no false counters or superficial success replies were added.

**No-obstruction-law review:** with slowlog armed, `slowlog_finish` serializes
history publication across owners. A GET completion can therefore wait for the
ring mutex held by another owner recording a SET. The default disarmed path does
not enter this mutex. This is a concrete cross-owner wait in optional logging,
and must be reviewed against the no-write-obstructed-read law before accepting
this root. The armed slowlog merit cells measure its cost; a rate result alone
cannot authorize an exception to that law.

LAT-HIST-2 preserves two clock reads per individual execution. This candidate
amortizes histogram bookkeeping and redundant commit flushing, not the duration
measurement itself. Literal batch-duration amortization would change Redis's
per-command distribution; that tradeoff needs an owner ruling. The reported 13%
loss has **not** been measured or claimed recovered here.

CPU process/children times use getrusage. Main-thread user/system times come from
Linux's main-TID stat counters (clock-tick precision), rather than incorrectly
reporting the INFO worker as the main thread. Build identity identifies TomoKV,
not the Redis oracle.

### Reproductions and falsification

`docs/infofix/pre-repros.json` replays the seven stored scripts unchanged against
PRE and Redis 7.4.10 at 16 shards, ratio 6:2, both modes. Every PRE verdict differs.
`post-repros.json` contains the corresponding earlier POST replay (before the
empty-histogram correction; final cold-root proof is in the 335-row run): DOCS, global
slowlog and offline LOADAOF are SAME in both modes. CPU text remains byte-different
because CPU numbers are volatile; the directed row checks its exact field schema,
format, selection, monotonicity and RESETSTAT behavior. Errorstats, commandstats,
and reload options remain DIFFERENT as reported above. LAT-HIST-2 has no stored
protocol reproduction; its performance reproduction is reserved to the maintainer.

All correctness listeners are 20400–20499, all work inherits CPUs 48–63, and builds
use `-j16`. Gate slots use server CPUs 48–55 and load CPUs 56–63, with explicit empty
load-SMT selection. The final epoll differential matrix reverses these two groups,
so the engines have disjoint eight-core servers and share only protocol-client
work with the opposite engine. Tcl and harness self-tests run after both finish. Oracle SHA-256:
`ac08d444fabe96073aff62e1d187497900b501b3d7667f727251d6d13f22509b`.
`/home/user/Projects/redis/src/redis-server` and the requested redis74 oracle have
that same digest.

The new rows run through `GATE_ONLY_JOBS` in `tests/gate.sh`:

- `infofix_compat-{missing,docs,slowlog,loadaof}` each run Redis plus 1s/2s ×
  uring/epoll × databases 1/16. PRE fails all four rows; frozen POST passes all four.
- `infofix_latency` checks both executor modes, tracking off/on, and batch 1/32.
  It requires one histogram lock per tracked GET batch, one exact sample per
  command, alternating 1 us/16 ms durations through the real executor, separate
  histogram bins, exactly two clocks per tracked command, and zero timing clocks
  or histogram allocation off. Allocated buckets without samples stay invisible.
  PRE and a POST mutant with `get_batch=false` both fail the batch witness; a
  shared-duration mutant fails the same row at its per-command distribution check.
  A fourth mutant exposing empty buckets fails the public histogram-reply check.
- A cold-root regression arm links POST with PRE t_server/cmdmeta/slowlog/xshard
  objects in both namespaces. Its four directed rows fail, and the promoted Tcl
  cases fail in both modes. This arm is only a negative control.

Receipts: `docs/infofix/{pre-directed-final,post-directed-final,regression,
latency-regression}.log`, the `evidence/` archives indexed by SHA-256 in `evidence/index.json`.
POST's new rows plus release and metadata validation: **7 pass, 0 fail**.
PRE: **1 pass, 5 intended failures**. Cold-root regression: **1 pass, 6 intended
failures** (four directed rows and two Tcl mode rows). Latency regression:
**1 pass, 1 intended failure**.

The Tcl manifest promotes the repaired slowlog/reload/CLI cases, adds all three
`unit/info-command` assertions, and requires `unit/printver`'s successful body
output. Missing, duplicate, incomplete and failed printver execution cannot pass.
Its harness self-test passes all 10 tests. Existing LATENCY HISTOGRAM assertions
were already required; there was no LAT-HIST-2 skip to remove. They are semantic
checks; the new serverless row discriminates the batching mechanism.

### Hot-path instruction budget

`docs/infofix/command-counts.tsv` and `counts/results-final.json` retain every
PRE/POST count and per-function detail with latency tracking and slowlog off: 48 paired cases across both database
runtimes, both thread modes, batches 1/32, GET/SET/INCR/MGET/MSET, and MSET atomic
0/1. **24 identical, 24 lower, zero increases.** GET/SET/INCR are identical in
every case. MGET/MSET have no increase.

Example PRE/POST instruction totals for a 32-command scope in the normal database
runtime (MSET uses atomic=1; all 48 pairs are in the TSV):

| Command | 1s PRE | 1s POST | 2s PRE | 2s POST |
|---|---:|---:|---:|---:|
| GET | 18482 | 18482 | 18327 | 18327 |
| SET | 22450 | 22450 | 22295 | 22295 |
| INCR | 37763 | 37763 | 37608 | 37608 |
| MGET | 324902 | 324486 | 324902 | 324486 |
| MSET | 961926 | 961574 | 951302 | 950950 |

The fixture is `tests/txnorder_command_scope.cc`, linked to each arm's production
objects. `tools/infofix_scope.py` single-steps only an owned, finite serverless
child; counts all selected production namespace instructions including NOPs;
excludes external library bodies; freezes clock_gettime; and requires the exact
reply/data checks to pass. These are command-scope counts, not cycles/IPC or a
throughput verdict. Initial positive scatter deltas are retained in
`counts-initial.json`; isolating AOF recovery as a cold function removed them.
The zero-added-instructions claim is for tracking/slowlog off. Armed GET/SET
performance, including the extra batch-context check in the generic armed
recorder, remains part of the merit request.

### Build and gate proof

Every gate invocation is a selected correctness job run. These are partial proof
records, not a full-gate or performance receipt.

**Final affected jobs: 335 pass, 0 fail**, including all five new rows.
`affected-post-final.log` and `evidence/affected-post-final.tar.gz` retain the
complete result. **Both full standard-seed differential matrices pass: 6 rows
each, 0 failures**, covering all four split/fused-read-local × atomic=0/1 parts
and mode equivalence. Seeds were 7,19,20,23,21,22 plus rotating 25 (uring) or
24 (epoll), with the normal MULTI repeats retained. See `differ-verdicts-final.json`
and the two final differential evidence archives. Final Tcl and gate-harness
self-test results are still being collected. `make all` and every production-unit
prerequisite rebuilt through the gate; all **56** target-specific `make -q` checks
pass in `production-freshness-final.json`. No earlier failure is discarded.
The initial affected run was 311 pass / 16 fail: eight stale INFO DEFAULT section
expectations, four stale LOADAOF error strings, and four downstream snapshot
checks after those interrupted recovery batteries. The expected replies were
updated to Redis's grammar; no assertion was removed. A subsequent run exposed
the native INFO fixture's fake PID; it now uses its real PID for the main-thread
CPU read and retains every protected-memory assertion. The old differential
DOCS assertion required replies to differ; it now requires a populated reply
identical to Redis. The superseded uring matrix failed only that assertion and
its non-vacuity counter; the superseded epoll run was interrupted for replacement.
Their original logs and receipts are retained.

Five public rows are collected at gate.sh lines 5981–5982, above the quick exit at
line 6114. **DQ=+5, DF=+5**. EXPECT_QUICK/EXPECT_FULL were not edited; the maintainer
should change **881→886** and **898→903**. Extending existing Tcl/metadata jobs
adds no public row.

### Frozen arms

| Arm | Binary | SHA-256 |
|---|---|---|
| PRE | `build/infofix/pre/tomokv` | `5285c0225adbdb8e1204548b010d68238c3358e242d5fab932f4c28a5369dd76` |
| POST | `build/infofix/post-final/tomokv` | `28faa60c3196fc531aa99b0a4d54947a46ae6533fcbd013ea9da852b9522da35` |
| PAD-A | `build/infofix/pad-a-final/tomokv` | `a4fd1c1d1ca188812f38493625b48d41069c267bb01871f8d8955d25056b00ac` |

PAD is **kind A: behaviour twin**: unmodified PRE production objects plus
unreachable padding, matching POST's .text start and total size, with additive
.rodata padding. Individual function/data placement is not identical to POST;
this is a text-size/layout control with that explicit limitation, not an exact
symbol-placement twin. `docs/infofix/arms-final.json` records section sizes, commands,
and regression-arm digest. `python3 tools/infofix_arms.py --tag final` recreates the links.
Superseded arm sources and step traces were deleted after their hashes/counts
were recorded in `retired-artifacts.json`. PRE objects and frozen binaries remain.

### Maintainer merit request

Performance benchmarks and full `tests/gate.sh iteration`: **NOT RUN**, reserved
to the maintainer. No throughput or latency improvement claim.

Use the gate's own quiet-box ABBA instrument, matched offered load, with PRE vs
POST, PRE vs PAD-A, and contemporaneous PRE/PRE controls. Record every arm's hash,
configuration, rate, cycles/op, instructions/op and IPC; keep the depth-1 latency
result. The off-path verdict must be null under the gate's normal criteria.

- `docs/infofix/generic14.cells.txt`: exact generic 14 (`h05 h06 p8g p8s d1g_l0
  d1s_l0 m8g_l0 v1g_l0 d128g_l0 d32g_l1 d8s_l1 d32s_l1 x9_32_l1 x9_32_l0`),
  latency tracking off.
- `null2s.cells.txt`: `h17 h18 h49 h50`, 2s GET/SET at p32/p1, tracking off, null.
- `scatter8.cells.txt`: MGET/MSET p1/p32 in both modes, since the AOF preparation
  change shares scatter dispatch. Run database runtimes 1 and 16 for this set.
- `armed8.cells.txt`: GET/SET p1/p32 in both modes with tracking yes on every arm.
  The decisive LAT-HIST-2 cell is **h17 (2s GET p32)**. Compare with the matching
  tracking-off cells to quantify armed cost. Preserve the exact histogram witnesses.
- `slowlog8.cells.txt`: GET/SET p1/p32 in both modes with threshold zero and max-len
  128, to quantify the global retention mutex while verifying the cap.
- `info-poll.cells.txt`: p32 GET in both modes with the existing INFO polling probe,
  covering the newly populated introspection fields.

Cold COMMAND DOCS and DEBUG replies/data are covered by the oracle rows, not
represented as throughput wins. A lower instruction count alone cannot decide
merit; if POST and PAD move together, investigate layout before crediting behavior.
